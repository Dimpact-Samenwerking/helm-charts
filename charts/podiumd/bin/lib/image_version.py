"""Update every values.yaml image tag pin whose repository's basename
matches a given image name — the "same base image pinned in more than one
place" case (e.g. curlimages/curl, used as a generic init-container/
health-check helper by more than one unrelated component) that a single
dotted-path update can't reach on its own. Shared by update-image-
version.py's own CLI and update-component-version.py: a component's app
version bump resolves to one or more of these basename updates — the
component name and the image name are not always the same (e.g.
zgw-office-addin bumps two distinctly-named images, frontend + backend)."""
from lib.chart import replace_scalar_value
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
