"""Update every values.yaml image tag pin whose repository's basename
matches a given image name — the "same base image pinned in more than one
place" case (e.g. curlimages/curl, used as a generic init-container/
health-check helper by more than one unrelated component) that a single
dotted-path update can't reach on its own. Shared by update-image-
version.py's own CLI and update-component-version: a component's app
version bump resolves to one or more of these basename updates — the
component name and the image name are not always the same (e.g.
zgw-office-addin bumps two distinctly-named images, frontend + backend)."""
from lib.chart import dotted_key_path, find_dependency, load_yaml, replace_scalar_value
from lib.image_digests import scan_digest_pins
from lib.registry import parse_repo, registry_tag_exists


def image_basename(repository):
    """The last "/"-separated segment of a repository string — "pabc-api"
    for "ghcr.io/platform-autorisatie-beheer-component/pabc-api", "curl"
    for "curlimages/curl"."""
    return repository.rstrip("/").rsplit("/", 1)[-1]


def find_matches(lines, basename):
    """Every scan_digest_pins() pin whose resolved repository has this
    basename. A pin with no resolvable repository (relies on a vendored
    sub-chart's own default — e.g. openzaak/openformulieren, see
    lib.chart.subchart_default_repository) can never match here: there's
    no explicit text in values.yaml to derive a basename from at all. A
    caller updating one of those resolves its repository another way and
    writes it directly, rather than through this basename search."""
    return [p for p in scan_digest_pins(lines) if p["repository"] and image_basename(p["repository"]) == basename]


def basenames_under_scope(lines, scope_key):
    """{basename: [pin, ...]} for every literal digest pin (see
    scan_digest_pins) whose values.yaml path starts with scope_key and
    ends in "...tag" — i.e. every image actually pinned somewhere inside
    that top-level component's own subtree. A basename maps to more than
    one pin only if the exact same image is pinned more than once under
    that same component. Shared by export-confluence-release-table's
    own image_basename resolution and resolve_basename below — pure
    values.yaml text, no release-table.csv involved either way."""
    result = {}
    for pin in scan_digest_pins(lines):
        if not pin["repository"]:
            continue
        path = dotted_key_path(lines, pin["line"] - 1).split(".")
        if path[0] != scope_key or path[-1] != "tag":
            continue
        result.setdefault(image_basename(pin["repository"]), []).append(pin)
    return result


def resolve_basename(chart_dir, lines, target):
    """The single image basename `target` actually identifies — either
    directly (a real basename with at least one digest pin already, the
    existing update-image-version CLI contract, tried first so this
    never changes behavior for a call that already works today), or via
    a Chart.yaml dependency's own name/alias (see lib.chart.
    find_dependency — an EXACT match, unlike export-confluence-release-
    table.py's own fuzzy component_and_alias: a CLI argument is a
    developer typing a known identifier, not free-form Confluence prose,
    so there's no ambiguity to hedge against there).

    A dependency resolves cleanly only when its own values.yaml scope
    (see basenames_under_scope) has EXACTLY ONE image pinned — e.g.
    "openklant" or "zaakbrug". Never guesses when a dependency owns
    several (e.g. "zac" has eight, "pabc" has three): raises SystemExit
    listing every candidate instead, same as when a dependency owns none
    at all (relies on a vendored sub-chart default, or a non-standard
    tag field this scanner can't see) or `target` matches neither a
    basename nor any dependency."""
    if find_matches(lines, target):
        return target

    chart_yaml_path = chart_dir / "Chart.yaml"
    deps = (load_yaml(chart_yaml_path) or {}).get("dependencies", []) if chart_yaml_path.is_file() else []
    dep = find_dependency(deps, target)
    if dep is None:
        raise SystemExit(f"error: '{target}' is not a pinned image basename, "
                          f"and no Chart.yaml dependency has that name or alias")

    scope_key = dep.get("alias") or dep["name"]
    available = basenames_under_scope(lines, scope_key)
    if not available:
        raise SystemExit(f"error: '{target}' resolves to Chart.yaml dependency '{dep['name']}', "
                          f"but no digest-pinned image was found under its own values.yaml scope "
                          f"(relies on a vendored sub-chart default, or uses a non-standard tag field)")
    if len(available) > 1:
        raise SystemExit(f"error: '{target}' resolves to Chart.yaml dependency '{dep['name']}', "
                          f"which pins {len(available)} distinct images — specify one directly: "
                          f"{', '.join(sorted(available))}")
    return next(iter(available))


def update_image_version(values_path, basename, new_version):
    """Update every values.yaml tag pin whose repository basename is
    `basename` to new_version, re-resolving each one's digest against the
    registry FIRST — before any file is touched, so a bad version name
    fails loudly instead of leaving values.yaml half-updated. Two matches
    sharing the same repository (the same image pinned twice) only need
    one registry lookup between them.

    Returns a list of dicts, one per line actually changed, in file order
    — empty if every match was already at new_version:
        {"line", "repository", "old_version", "old_digest",
         "new_version", "new_digest"}

    Raises SystemExit if no pin matches basename at all, or if new_version
    doesn't exist upstream for some matched repository."""
    text = values_path.read_text(encoding="utf-8")
    plain_lines = text.splitlines()
    matches = find_matches(plain_lines, basename)
    if not matches:
        raise SystemExit(f"error: no image pin with basename '{basename}' found in {values_path}")

    pending = [m for m in matches if m["version"] != new_version]
    if not pending:
        return []

    digests = {}
    for m in pending:
        if m["repository"] in digests:
            continue
        host, repo_path = parse_repo(m["repository"])
        exists, digest = registry_tag_exists(host, repo_path, new_version)
        if not exists or not digest:
            raise SystemExit(f"error: {host}/{repo_path}:{new_version} not found upstream")
        digests[m["repository"]] = digest

    write_lines = text.splitlines(keepends=True)
    changes = []
    for m in pending:
        digest = digests[m["repository"]]
        write_lines[m["line"] - 1] = replace_scalar_value(write_lines[m["line"] - 1], f"{new_version}@{digest}")
        changes.append({
            "line": m["line"], "repository": m["repository"],
            "old_version": m["version"], "old_digest": f"sha256:{m['digest']}",
            "new_version": new_version, "new_digest": digest,
        })
    values_path.write_text("".join(write_lines), encoding="utf-8")
    return changes
