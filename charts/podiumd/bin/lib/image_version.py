"""Update every values.yaml image tag pin whose repository's basename
matches a given image name, scoped to a given top-level values.yaml key
(a component, or MULTIPLE_KEY for a base image shared across several
unrelated components via values.yaml's global.images anchor block — e.g.
curlimages/curl, used as a generic init-container/health-check helper) —
the "same base image pinned in more than one place" case a single
dotted-path update can't reach on its own. Shared by update-image-
version.py's own CLI and update-component-version: a component's app
version bump resolves to one or more of these basename updates — the
component name and the image name are not always the same (e.g.
zgw-office-addin bumps two distinctly-named images, frontend + backend)."""
from lib.chart import dotted_key_path, replace_scalar_value
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
    own image_basename resolution — pure values.yaml text, no
    release-table.csv involved either way."""
    result = {}
    for pin in scan_digest_pins(lines):
        if not pin["repository"]:
            continue
        path = dotted_key_path(lines, pin["line"] - 1).split(".")
        if path[0] != scope_key or path[-1] != "tag":
            continue
        result.setdefault(image_basename(pin["repository"]), []).append(pin)
    return result


# release-table.csv's own convention (see export-confluence-release-
# table's component_and_alias) for a base image shared across several
# unrelated components via values.yaml's global.images anchor block
# (nginx, curl, busybox, redis — pinned once, aliased everywhere else),
# rather than owned by any single component. Re-used here, instead of
# each caller keeping its own copy, so update-image-version/verify-
# image-version/show-image-baseline-version and verify-release-table-
# with-podiumd all agree on exactly what "MULTIPLE" means.
MULTIPLE_KEY = "MULTIPLE"
GLOBAL_IMAGES_SCOPE = "global"


def find_matches_in_scope(lines, scope_key, basename):
    """Every scan_digest_pins() pin whose values.yaml path starts with
    scope_key AND whose resolved repository has this basename — the same
    search as find_matches, but scoped to one top-level component so the
    same basename pinned under two unrelated components can't be
    confused for each other."""
    matches = []
    for pin in scan_digest_pins(lines):
        if not pin["repository"] or image_basename(pin["repository"]) != basename:
            continue
        path = dotted_key_path(lines, pin["line"] - 1).split(".")
        if path[0] != scope_key:
            continue
        matches.append(pin)
    return matches


def resolve_scoped_matches(lines, key, basename):
    """The pins <key> <basename> together identify, uniquely. <key> is
    either a literal top-level values.yaml key (a component), or the
    literal string "MULTIPLE" (see MULTIPLE_KEY above), translated to
    GLOBAL_IMAGES_SCOPE.

    Raises SystemExit if nothing matches under that scope (a bad key, a
    bad basename, or a real image that isn't actually pinned there), or
    if more than one DISTINCT repository matches (the basename genuinely
    isn't unique under this scope — e.g. two unrelated repositories
    happen to share a last path segment) — <key> <basename> must
    identify exactly one image, never a guess."""
    scope_key = GLOBAL_IMAGES_SCOPE if key == MULTIPLE_KEY else key
    matches = find_matches_in_scope(lines, scope_key, basename)
    if not matches:
        raise SystemExit(f"error: no image pin with basename '{basename}' found under '{key}'")
    repositories = {m["repository"] for m in matches}
    if len(repositories) > 1:
        raise SystemExit(f"error: '{basename}' under '{key}' is not unique — "
                          f"{len(repositories)} distinct repositories match: "
                          f"{', '.join(sorted(repositories))}")
    return matches


def check_basename_version(lines, key, basename, new_version):
    """[{"repository", "host", "repo_path", "exists", "digest"}, ...] one
    for <key> <basename>'s single resolved repository (see
    resolve_scoped_matches — it never returns more than one distinct
    repository), checked against new_version on its actual upstream
    registry. Read-only — never writes — shared by verify-image-version
    (a human pre-checking a version before writing it anywhere) and could
    be reused by update_image_version's own upfront verification gate
    above, though that one currently keeps its inline loop since it also
    needs the digest values it collects.

    Raises SystemExit if <key> <basename> doesn't resolve uniquely (see
    resolve_scoped_matches)."""
    matches = resolve_scoped_matches(lines, key, basename)

    results = []
    seen_repositories = set()
    for m in matches:
        if m["repository"] in seen_repositories:
            continue
        seen_repositories.add(m["repository"])
        host, repo_path = parse_repo(m["repository"])
        exists, digest = registry_tag_exists(host, repo_path, new_version)
        results.append({"repository": m["repository"], "host": host, "repo_path": repo_path,
                         "exists": exists, "digest": digest})
    return results


def update_image_version(values_path, key, basename, new_version):
    """Update every values.yaml tag pin <key> <basename> resolves to (see
    resolve_scoped_matches) to new_version, re-resolving each one's
    digest against the registry FIRST — before any file is touched, so a
    bad version name fails loudly instead of leaving values.yaml
    half-updated. Two matches sharing the same repository (the same
    image pinned twice under this scope) only need one registry lookup
    between them.

    Returns a list of dicts, one per line actually changed, in file order
    — empty if every match was already at new_version:
        {"line", "repository", "old_version", "old_digest",
         "new_version", "new_digest"}

    Raises SystemExit if <key> <basename> doesn't resolve uniquely (see
    resolve_scoped_matches), or if new_version doesn't exist upstream for
    the matched repository."""
    text = values_path.read_text(encoding="utf-8")
    plain_lines = text.splitlines()
    matches = resolve_scoped_matches(plain_lines, key, basename)

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
