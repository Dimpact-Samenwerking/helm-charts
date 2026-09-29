"""Find and update values.yaml image pins by repository basename within a top-level key (or MULTIPLE).

Covers one image pinned in several places; update-component-version uses it
too, as a component's images may be named differently (zgw-office-addin).
"""

from pathlib import Path
from typing import TypedDict
from typing import TypeVar

from lib.chart.chart_yaml import ChartDependency
from lib.chart.values_tree_primitives import dotted_key_path
from lib.chart.values_tree_primitives import find_dependency
from lib.chart.values_tree_primitives import replace_scalar_value
from lib.chart.values_tree_primitives import same_name
from lib.chart.values_tree_primitives import values_key_of
from lib.image.digests import DigestPin
from lib.image.digests import VersionPin
from lib.image.digests import scan_digest_pins
from lib.image.digests import scan_version_pins
from lib.registry import TagCheck
from lib.registry import parse_repo
from lib.registry import registry_tag_exists


class PinUpdate(TypedDict):
    """One values.yaml pin update_image_version rewrote."""

    line: int
    repository: str
    old_version: str
    old_digest: str
    new_version: str
    new_digest: str


class ScopedPin(TypedDict):
    """A DigestPin find_matches_in_scope matched, so its repository is known."""

    line: int
    version: str
    digest: str
    repository: str


def image_basename(repository: str) -> str:
    """The last "/" segment of `repository`, e.g. "curl" for "curlimages/curl"."""
    return repository.rstrip("/").rsplit("/", 1)[-1]


def find_matches(lines: list[str], basename: str) -> list[DigestPin]:
    """Every scan_digest_pins() pin whose resolved repository has this basename.

    Pins relying on a subchart-default repository never match.
    """
    return [
        p for p in scan_digest_pins(lines) if p["repository"] and same_name(image_basename(p["repository"]), basename)
    ]


def find_matches_any_tag(lines: list[str], basename: str) -> list[VersionPin]:
    """find_matches over scan_version_pins, so bare tags match too.

    Only for release-table comparisons (the CSV has no digests); writers and
    digest checks must use find_matches.
    """
    return [
        p for p in scan_version_pins(lines) if p["repository"] and same_name(image_basename(p["repository"]), basename)
    ]


def basenames_under_scope(lines: list[str], scope_key: str) -> dict[str, list[DigestPin]]:
    """{basename: [pin, ...]} for every digest pin under top-level `scope_key` ending in "...tag"."""
    return _group_by_basename_in_scope(lines, scan_digest_pins(lines), scope_key)


def basenames_under_scope_any_tag(lines: list[str], scope_key: str) -> dict[str, list[VersionPin]]:
    """basenames_under_scope over scan_version_pins, so bare tags count too.

    For release-table comparisons, and as the export's fallback when a scope
    has no digest pin at all (e.g. omc, whose subchart can't take a digest).
    """
    return _group_by_basename_in_scope(lines, scan_version_pins(lines), scope_key)


PinT = TypeVar("PinT", DigestPin, VersionPin)


def _group_by_basename_in_scope(lines: list[str], pins: list[PinT], scope_key: str) -> dict[str, list[PinT]]:
    """{basename: [pin, ...]} for the `pins` whose values.yaml path is
    under top-level `scope_key` (ignoring case, like find_matches_in_
    scope) and ends in "...tag"."""
    result: dict[str, list[PinT]] = {}
    for pin in pins:
        if not pin["repository"]:
            continue
        path = dotted_key_path(lines, pin["line"] - 1).split(".")
        if not same_name(path[0], scope_key) or path[-1] != "tag":
            continue
        result.setdefault(image_basename(pin["repository"]), []).append(pin)
    return result


def repository_for_basename_in_scope(lines: list[str], scope_key: str, basename: str) -> str | None:
    """The one repository <scope_key>.<image-basename> resolves to in `lines`, or None.

    Scoped match first, else the unscoped find_matches_any_tag (e.g.
    keycloak-config-cli lives under "keycloak", not "keycloak-operator").
    None if several distinct repositories match: basenames can collide
    ("redis" is both global.images.redis and quay.io/opstree/redis), and
    callers use this as a trusted anchor across chart states.
    """
    scoped = basenames_under_scope_any_tag(lines, scope_key).get(basename)
    pins = scoped or find_matches_any_tag(lines, basename)
    if not pins:
        return None
    repos = {p["repository"] for p in pins if p["repository"]}
    return next(iter(repos)) if len(repos) == 1 else None


# release-table.csv's key for a base image shared via global.images rather than owned by one component.
MULTIPLE_KEY = "MULTIPLE"
GLOBAL_IMAGES_SCOPE = "global"


def resolve_key_scope(key: str, deps: list[ChartDependency]) -> str:
    """The top-level values.yaml key for CLI <key>, mapping a dependency's name or alias to it.

    MULTIPLE_KEY and keys matching no dependency (components defined in
    podiumd itself, typos) pass through; resolve_scoped_matches reports a bad one.
    """
    if same_name(key, MULTIPLE_KEY):
        return MULTIPLE_KEY
    dep = find_dependency(deps, key)
    return values_key_of(dep) if dep is not None else key


def find_matches_in_scope(lines: list[str], scope_key: str, basename: str) -> list[ScopedPin]:
    """find_matches restricted to pins under top-level `scope_key`."""
    matches: list[ScopedPin] = []
    for pin in scan_digest_pins(lines):
        repository = pin["repository"]
        if not repository or not same_name(image_basename(repository), basename):
            continue
        path = dotted_key_path(lines, pin["line"] - 1).split(".")
        if not same_name(path[0], scope_key):
            continue
        matches.append(
            {"line": pin["line"], "version": pin["version"], "digest": pin["digest"], "repository": repository}
        )
    return matches


def resolve_scoped_matches(lines: list[str], key: str, basename: str) -> list[ScopedPin]:
    """The pins <key> <image-basename> identify; <key> is a top-level key or "MULTIPLE" (global.images).

    Raises SystemExit if nothing matches or more than one distinct
    repository does.
    """
    scope_key = GLOBAL_IMAGES_SCOPE if same_name(key, MULTIPLE_KEY) else key
    matches = find_matches_in_scope(lines, scope_key, basename)
    if not matches:
        msg = f"error: no image pin with image basename '{basename}' found under '{key}'"
        raise SystemExit(msg)
    repositories = {m["repository"] for m in matches}
    if len(repositories) > 1:
        msg = (
            f"error: '{basename}' under '{key}' is not unique — "
            f"{len(repositories)} distinct repositories match: "
            f"{', '.join(sorted(repositories))}"
        )
        raise SystemExit(msg)
    return matches


def check_basename_version(lines: list[str], key: str, basename: str, new_version: str) -> list[TagCheck]:
    """Read-only registry check of new_version for <key> <image-basename>'s single repository.

    Raises SystemExit if <key> <image-basename> doesn't resolve uniquely.
    """
    matches = resolve_scoped_matches(lines, key, basename)

    results: list[TagCheck] = []
    seen_repositories: set[str] = set()
    for m in matches:
        if m["repository"] in seen_repositories:
            continue
        seen_repositories.add(m["repository"])
        host, repo_path = parse_repo(m["repository"])
        exists, digest = registry_tag_exists(host, repo_path, new_version)
        results.append(
            {"repository": m["repository"], "host": host, "repo_path": repo_path, "exists": exists, "digest": digest}
        )
    return results


def _resolve_pending_digests(pending: list[ScopedPin], new_version: str) -> dict[str, str]:
    """{repository: digest} at new_version for each distinct repository in `pending`.

    Raises SystemExit if new_version is missing upstream, before anything is written.
    """
    digests: dict[str, str] = {}
    for m in pending:
        if m["repository"] in digests:
            continue
        host, repo_path = parse_repo(m["repository"])
        exists, digest = registry_tag_exists(host, repo_path, new_version)
        if not exists or not digest:
            msg = f"error: {host}/{repo_path}:{new_version} not found upstream"
            raise SystemExit(msg)
        digests[m["repository"]] = digest
    return digests


def plan_image_version_update(values_path: Path, key: str, basename: str, new_version: str) -> list[PinUpdate]:
    """The pin updates update_image_version would write, resolved but not written.

    Returns one dict per line to change, in file order ([] if all current).
    Raises SystemExit if <key> <image-basename> doesn't resolve uniquely or
    new_version doesn't exist upstream.
    """
    matches = resolve_scoped_matches(values_path.read_text(encoding="utf-8").splitlines(), key, basename)
    pending = [m for m in matches if m["version"] != new_version]
    if not pending:
        return []
    digests = _resolve_pending_digests(pending, new_version)
    return [
        {
            "line": m["line"],
            "repository": m["repository"],
            "old_version": m["version"],
            "old_digest": f"sha256:{m['digest']}",
            "new_version": new_version,
            "new_digest": digests[m["repository"]],
        }
        for m in pending
    ]


def write_pin_updates(values_path: Path, updates: list[PinUpdate]) -> None:
    """Write `updates` (from plan_image_version_update) into values_path."""
    if not updates:
        return
    lines = values_path.read_text(encoding="utf-8").splitlines(keepends=True)
    for u in updates:
        lines[u["line"] - 1] = replace_scalar_value(lines[u["line"] - 1], f"{u['new_version']}@{u['new_digest']}")
    values_path.write_text("".join(lines), encoding="utf-8")


def update_image_version(values_path: Path, key: str, basename: str, new_version: str) -> list[PinUpdate]:
    """Update every pin <key> <image-basename> resolves to to new_version, resolving digests before writing.

    Resolving first means a bad version never leaves values.yaml half-updated.
    Returns one dict per changed line, in file order ([] if all current):
        {"line", "repository", "old_version", "old_digest",
         "new_version", "new_digest"}

    Raises SystemExit if <key> <image-basename> doesn't resolve uniquely or
    new_version doesn't exist upstream.
    """
    changes = plan_image_version_update(values_path, key, basename, new_version)
    write_pin_updates(values_path, changes)
    return changes
