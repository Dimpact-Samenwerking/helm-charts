"""Report-only check that every digest-pinned image in values.yaml matches its live upstream digest."""

import re
import urllib.error

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Literal
from typing import TypedDict
from typing import TypeVar

from lib.chart.chart_yaml import ChartDependency
from lib.chart.chart_yaml import load_chart_dependencies
from lib.chart.repo_and_path_resolution import SubchartValuesCache
from lib.chart.repo_and_path_resolution import subchart_default_repository
from lib.registry import UNVERIFIABLE_HOSTS
from lib.registry import is_sliding_tag
from lib.registry import parse_repo
from lib.registry import registry_tag_exists
from lib.repo_access_cache import cache_entry_is_fresh as repo_access_entry_is_fresh
from lib.repo_access_cache import cache_key as repo_access_cache_key
from lib.repo_access_cache import load_cache as load_repo_access_cache
from lib.repo_access_cache import save_cache as save_repo_access_cache
from lib.settings import repo_access_cache_ttl_minutes

# One "tag:" pin, quoted or bare, optionally with an "&anchor"; digest None for a bare
# tag ("tag: <version>[@sha256:<digest>]"). scan_digest_pins keeps the pins with a digest.
# An alias ("tag: *anchor") has no value to read and doesn't match.
VERSION_PIN_RE = re.compile(
    r'^(?P<indent>\s*)tag:\s*(?:&\S+\s+)?"?(?P<version>[\w][\w.\-]*)(?:@sha256:(?P<digest>[0-9a-f]{64}))?"?\s*(?:#.*)?$'
)
# An active sibling "repository:" key, "&anchor" tolerated.
ACTIVE_REPO_RE = re.compile(
    r'^(?P<indent>\s*)repository:\s*(?:&\S+\s+)?"?(?P<repo>[\w][\w.\-]*(?:/[\w.\-]+)*)"?\s*(?:#.*)?$'
)
# An active sibling "registry:" key (split host style, e.g. redis-ha's opstree/redis).
# podiumd.image renders both styles the same, so resolve_pin_repo must honour it.
ACTIVE_REGISTRY_RE = re.compile(r'^(?P<indent>\s*)registry:\s*(?:&\S+\s+)?"?(?P<registry>[\w][\w.\-]*)"?\s*(?:#.*)?$')
# A commented-out "#repository: <value>" key, left as a hint for components
# whose real repository is overridden at the gemeente/deployment level.
COMMENTED_REPO_RE = re.compile(r'^\s*#\s*repository:\s*"?(?P<repo>[\w][\w.\-]*(?:/[\w.\-]+)*)"?\s*$')
# A one-line "# host/repo:tag[@sha256:...]" reference comment, placed above
# the "image:" block for the same override components. Tolerates a stray
# "@" right after the colon, seen on one existing comment in values.yaml.
REF_COMMENT_RE = re.compile(
    r"^\s*#\s*(?P<repo>[a-zA-Z0-9][\w.\-]*(?:/[\w.\-]+)*):@?[\w][\w.\-]*(?:@sha256:[0-9a-f]{64})?\s*$"
)


class DigestPin(TypedDict):
    """One "tag: <version>@sha256:<digest>" line of values.yaml; line is 1-based."""

    line: int
    version: str
    digest: str
    repository: str | None


class VersionPin(TypedDict):
    """One "tag:" line of values.yaml; digest is None for a bare tag."""

    line: int
    version: str
    digest: str | None
    repository: str | None


class RepeatedPin(TypedDict):
    """A repository pinned literally in more than one place (see
    find_inconsistent_version_pins): "duplicate" when every pin agrees,
    "drift" when they differ; pins groups the lines by (version, digest)."""

    kind: Literal["duplicate", "drift"]
    pins: list[tuple[tuple[str, str], list[int]]]


def _sibling_field(lines: list[str], tag_line_index: int, tag_indent: int, field_re: re.Pattern[str]) -> str | None:
    """The value (group 2, after the indent) of the nearest line above the pin that `field_re` matches.

    Only lines at the pin's own indent count, and the search stops at the end of its block."""
    for i in range(tag_line_index - 1, max(tag_line_index - 15, -1), -1):
        raw = lines[i]
        if not raw.strip():
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        if indent < tag_indent:
            break
        m = field_re.match(raw)
        if m and indent == tag_indent:
            return m.group(2)
    return None


def find_sibling_registry(lines: list[str], tag_line_index: int, tag_indent: int):
    """The sibling "registry:" value at the pin's indent (split host style), or None."""
    return _sibling_field(lines, tag_line_index, tag_indent, ACTIVE_REGISTRY_RE)


def find_inconsistent_version_pins(pins: list[DigestPin]) -> dict[str, RepeatedPin]:
    """Repositories pinned as a literal (non-alias) "tag:" in more than one place; always a problem.

    "duplicate": all pins agree, but one should alias the other's anchor or
    they will drift on the next bump. "drift": versions or digests differ
    (a deliberate variant would also have to fail here).

    Grouped by the exact repository string, not basename (docker.io/x/tool
    and ghcr.io/y/tool differ). Returns {repository: {"kind": ...,
    "pins": [((version, digest), [line, ...]), ...]}}; single pins omitted.
    """
    by_repo: dict[str, list[tuple[str, str, int]]] = {}
    for p in pins:
        if not p["repository"]:
            continue
        by_repo.setdefault(p["repository"], []).append((p["version"], p["digest"], p["line"]))

    findings: dict[str, RepeatedPin] = {}
    for repo, entries in by_repo.items():
        if len(entries) < 2:
            continue
        pairs: dict[tuple[str, str], list[int]] = {}
        for version, digest, line in entries:
            pairs.setdefault((version, digest), []).append(line)
        findings[repo] = {"kind": "duplicate" if len(pairs) == 1 else "drift", "pins": list(pairs.items())}
    return findings


def resolve_pin_repo(lines: list[str], tag_line_index: int, tag_indent: int) -> str | None:
    """The upstream repository of the "tag:" pin at tag_line_index, or None.

    Usually the sibling "repository:". Components that comment it out for
    gemeente ACR-mirror overrides (office_converter, opa, solr-operator)
    fall back to a "# host/repo:tag" comment above "image:" or a
    "#repository:" line. A sibling "registry:" is prefixed when present.
    """
    repo = _sibling_field(lines, tag_line_index, tag_indent, ACTIVE_REPO_RE)
    if repo is not None:
        registry = find_sibling_registry(lines, tag_line_index, tag_indent)
        return f"{registry}/{repo}" if registry else repo
    for i in range(tag_line_index - 1, max(tag_line_index - 6, -1), -1):
        m = REF_COMMENT_RE.match(lines[i])
        if m:
            return m.group("repo")
    for i in range(tag_line_index - 1, max(tag_line_index - 6, -1), -1):
        raw = lines[i]
        m = COMMENTED_REPO_RE.match(raw)
        if m and len(raw) - len(raw.lstrip(" ")) == tag_indent:
            return m.group("repo")
    return None


def scan_digest_pins(lines: list[str]) -> list[DigestPin]:
    """One record per "tag: <version>@sha256:<digest>" pin, with its resolved repository."""
    return [
        {"line": p["line"], "version": p["version"], "digest": digest, "repository": p["repository"]}
        for p in scan_version_pins(lines)
        if (digest := p["digest"]) is not None
    ]


def scan_version_pins(lines: list[str]) -> list[VersionPin]:
    """Every "tag:" pin with its resolved repository, digest None for a bare tag.

    scan_digest_pins keeps the pins that have a digest.
    """
    pins: list[VersionPin] = []
    for i, raw in enumerate(lines):
        m = VERSION_PIN_RE.match(raw)
        if not m:
            continue
        indent = len(m.group("indent"))
        pins.append(
            {
                "line": i + 1,
                "version": m.group("version"),
                "digest": m.group("digest"),
                "repository": resolve_pin_repo(lines, i, indent),
            }
        )
    return pins


def unique_digest_pin_targets(values_lines: list[str]) -> dict[tuple[str, str], tuple[str, int]]:
    """{(repository, version): (digest, line)} of the first pin per target resolvable from values.yaml alone.

    No subchart-default fallback (see resolve_pin_targets for that).
    """
    return {
        target: (pins[0]["digest"], pins[0]["line"])
        for target, pins in group_pins_by_target(scan_digest_pins(values_lines)).items()
    }


def group_pins_by_target(pins: list[DigestPin]) -> dict[tuple[str, str], list[DigestPin]]:
    """Pins with a repository, grouped by (repository, version) so each is fetched once."""
    targets: dict[tuple[str, str], list[DigestPin]] = {}
    for p in pins:
        if p["repository"]:
            targets.setdefault((p["repository"], p["version"]), []).append(p)
    return targets


def fill_pin_repositories(
    chart_dir: Path, lines: list[str], pins: list[DigestPin], deps: list[ChartDependency]
) -> None:
    """Set each pin without a repository to its vendored subchart's default one, when there is one."""
    subchart_cache: SubchartValuesCache = {}
    for p in pins:
        if not p["repository"]:
            p["repository"] = subchart_default_repository(chart_dir, lines, p["line"], deps, subchart_cache)


def resolve_pin_targets(chart_dir: Path) -> tuple[list[DigestPin], dict[tuple[str, str], list[DigestPin]]]:
    """(pins, {(repository, version): [pin, ...]}), repositories falling back to the subchart default."""
    values_path = chart_dir / "values.yaml"
    lines = values_path.read_text(encoding="utf-8").splitlines()
    pins = scan_digest_pins(lines)

    chart_yaml_path = chart_dir / "Chart.yaml"
    deps = load_chart_dependencies(chart_yaml_path) if chart_yaml_path.is_file() else []
    fill_pin_repositories(chart_dir, lines, pins, deps)
    return pins, group_pins_by_target(pins)


_tag_exists_cache: dict[tuple[str, str], tuple[bool, str | None]] = {}


def clear_tag_exists_cache() -> None:
    """Empty cached_tag_exists' in-process tier; the disk cache stays."""
    _tag_exists_cache.clear()


def cached_tag_exists(
    chart_dir: Path, repository: str, version: str, timeout: float | None = None
) -> tuple[bool, str | None]:
    """registry_tag_exists keyed on (repository, version), cached so steps in one run share lookups.

    Tiers: an in-process dict, then the disk store of lib.repo_access_cache
    (same entry format, extended with "digest", so repo-access and
    image-digests share it). Only found tags are persisted: a 404 may be
    transient. Exceptions are never cached, so callers' retries really
    retry. `timeout` is passed through on a miss.
    """
    host, repo_path = parse_repo(repository)
    key = (repository, version)
    if key in _tag_exists_cache:
        return _tag_exists_cache[key]

    disk_key = repo_access_cache_key("registry", (host, repo_path, version))
    disk_cache = load_repo_access_cache(chart_dir)
    disk_entry = disk_cache.get(disk_key)
    ttl_minutes = repo_access_cache_ttl_minutes(chart_dir)
    if disk_entry and repo_access_entry_is_fresh(disk_entry, ttl_minutes) and "digest" in disk_entry:
        result = (True, disk_entry["digest"])
        _tag_exists_cache[key] = result
        return result

    # Only pass timeout= when given: test mocks take (host, repo, tag) only.
    result = (
        registry_tag_exists(host, repo_path, version, timeout=timeout)
        if timeout is not None
        else registry_tag_exists(host, repo_path, version)
    )
    _tag_exists_cache[key] = result

    exists, digest = result
    if exists:
        disk_cache[disk_key] = {
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "digest": digest,
        }
        save_repo_access_cache(chart_dir, disk_cache)

    return result


def find_sliding_pins(chart_dir: Path) -> list[tuple[str, str, str, str]]:
    """[(repository, version, pinned_digest, digest)] for every pin whose upstream digest has slid.

    Mismatches that aren't sliding, fetch errors and unverifiable pins are
    left to check_image_digests. Shares cached_tag_exists with it. Silent:
    check_image_digests already announces each pin.
    """
    values_path = chart_dir / "values.yaml"
    _pins, targets = resolve_pin_targets(chart_dir)

    sliding: list[tuple[str, str, str, str]] = []
    for (repository, version), group in sorted(targets.items()):
        host, repo_path = parse_repo(repository)
        pinned_digest = group[0]["digest"]
        try:
            exists, digest = cached_tag_exists(chart_dir, repository, version)
        except (urllib.error.URLError, OSError):  # noqa: S112 -- silent by design, see docstring
            continue
        if not exists or not digest or digest == f"sha256:{pinned_digest}":
            continue
        if is_sliding_tag(values_path, host, repo_path, version, digest):
            sliding.append((repository, version, pinned_digest, digest))
    return sliding


@dataclass
class PinLocation:
    """One pin's repository, parsed once into host/repo_path, and version."""

    repository: str
    host: str
    repo_path: str
    version: str


@dataclass
class PinCheckContext:
    """One pin's per-iteration state, built by _build_pin_context."""

    chart_dir: Path
    values_path: Path
    pinned_digest: str
    lines_str: str
    loc: PinLocation


# (repository, version, pinned_digest, upstream_digest, lines) of a pin
# whose upstream digest differs.
DigestMismatch = tuple[str, str, str, str, str]
# (repository, version, error, lines) of a pin whose lookup failed.
PinFailure = tuple[str, str, str | None, str]
# (repository, version, pinned_digest, lines) of a pin whose digest is
# gone upstream.
GonePin = tuple[str, str, str, str]


@dataclass
class DigestCheckAccumulator:
    """Matched count and one list per outcome, filled by _process_pin."""

    matched: int
    mismatches: list[DigestMismatch]
    sliding_mismatches: list[DigestMismatch]
    fetch_errors: list[PinFailure]
    unverifiable: list[PinFailure]
    digest_gone: list[GonePin]
    digest_check_errors: list[PinFailure]


ResultT = TypeVar("ResultT")


def _call_with_retry(fn: Callable[[], ResultT]) -> tuple[ResultT | None, str | None]:
    """Call fn(), retrying once on a transient network error.

    Returns (result, error); result is None only when both attempts raised.
    """
    result, error = None, None
    for _attempt in range(2):
        try:
            result = fn()
            error = None
            break
        except (urllib.error.URLError, OSError) as e:
            error = str(e)
    return (result, None) if error is None else (None, error)


def _build_pin_context(
    chart_dir: Path, values_path: Path, repository: str, version: str, group: list[DigestPin]
) -> PinCheckContext:
    """The PinCheckContext of one (repository, version) pin group."""
    host, repo_path = parse_repo(repository)
    pinned_digest = group[0]["digest"]
    lines_str = ", ".join(str(p["line"]) for p in group)
    loc = PinLocation(repository, host, repo_path, version)
    return PinCheckContext(chart_dir, values_path, pinned_digest, lines_str, loc)


def _resolve_pin_tag_status(ctx: PinCheckContext):
    """(digest, error) of the pin's tag lookup, retried once; error "tag not found upstream" on a 404."""
    result, error = _call_with_retry(lambda: cached_tag_exists(ctx.chart_dir, ctx.loc.repository, ctx.loc.version))
    if result is None:
        return None, error
    exists, digest = result
    return digest, (None if exists else "tag not found upstream")


def _classify_pin_tag_result(ctx: PinCheckContext, digest: str | None, error: str | None, acc: DigestCheckAccumulator):
    """Print and record one pin's tag-lookup outcome; whether the digest-still-resolvable check is warranted."""
    host, repo_path, version = ctx.loc.host, ctx.loc.repo_path, ctx.loc.version
    repository = ctx.loc.repository

    if error and host in UNVERIFIABLE_HOSTS:
        acc.unverifiable.append((repository, version, error, ctx.lines_str))
        print(f"  [UNVERIFIABLE] {host}/{repo_path}:{version}  {error}  (values.yaml:{ctx.lines_str})")
        return False
    if error:
        acc.fetch_errors.append((repository, version, error, ctx.lines_str))
        print(f"  [FETCH-ERR] {host}/{repo_path}:{version}  {error}  (values.yaml:{ctx.lines_str})")
        return True
    if digest and digest != f"sha256:{ctx.pinned_digest}":
        sliding = is_sliding_tag(ctx.values_path, host, repo_path, version, digest)
        entry = (repository, version, ctx.pinned_digest, digest, ctx.lines_str)
        if sliding:
            acc.sliding_mismatches.append(entry)
            print(f"  [SLIDING  ] {host}/{repo_path}:{version}  (known to drift — refresh with fix-image-digests)")
        else:
            acc.mismatches.append(entry)
            print(f"  [MISMATCH ] {host}/{repo_path}:{version}")
        print(f"      pinned:   sha256:{ctx.pinned_digest}")
        print(f"      upstream: {digest}")
        print(f"      lines:    values.yaml:{ctx.lines_str}")
        return True
    if not digest:
        # No Docker-Content-Digest header (some registries/proxies strip it): can't confirm the
        # pin, so count it as unverifiable, not matched.
        reason = "registry returned no digest header"
        acc.unverifiable.append((repository, version, reason, ctx.lines_str))
        print(f"  [UNVERIFIABLE] {host}/{repo_path}:{version}  {reason}  (values.yaml:{ctx.lines_str})")
        return True
    acc.matched += 1
    return False


def _confirm_pinned_digest_still_resolvable(ctx: PinCheckContext, acc: DigestCheckAccumulator):
    """Report [DIGEST-GONE] when the pinned digest itself no longer resolves upstream.

    Then `helm install` would fail now, even if the tag finding was only a
    warning.
    """
    host, repo_path, repository, version = ctx.loc.host, ctx.loc.repo_path, ctx.loc.repository, ctx.loc.version
    digest_ref = f"sha256:{ctx.pinned_digest}"
    result, digest_error = _call_with_retry(lambda: registry_tag_exists(host, repo_path, digest_ref))

    if result is None:
        acc.digest_check_errors.append((repository, version, digest_error, ctx.lines_str))
        print(
            f"  [FETCH-ERR] {host}/{repo_path}@{digest_ref}  {digest_error}  (while "
            f"confirming the currently-pinned digest is still pullable, "
            f"values.yaml:{ctx.lines_str})"
        )
        return

    digest_exists, _ = result
    if not digest_exists:
        acc.digest_gone.append((repository, version, ctx.pinned_digest, ctx.lines_str))
        print(
            f"  [DIGEST-GONE] {host}/{repo_path}@{digest_ref}  the EXACT digest "
            f"values.yaml pins TODAY is no longer resolvable upstream at all — "
            f"helm install/upgrade would fail outright right now "
            f"(values.yaml:{ctx.lines_str})"
        )


def _process_pin(ctx: PinCheckContext, i: int, total: int, acc: DigestCheckAccumulator):
    """Announce and check one pin; every pin is announced since each is a real registry call."""
    print(f"  [{i}/{total}] checking {ctx.loc.host}/{ctx.loc.repo_path}:{ctx.loc.version}...", flush=True)
    digest, error = _resolve_pin_tag_status(ctx)
    needs_digest_check = _classify_pin_tag_result(ctx, digest, error, acc)
    if needs_digest_check and ctx.loc.host not in UNVERIFIABLE_HOSTS:
        _confirm_pinned_digest_still_resolvable(ctx, acc)


def _print_unresolved_pins(unresolved: list[DigestPin]):
    """Print pins without a resolvable repository; skipped, not a failure."""
    if not unresolved:
        return
    print(f"{len(unresolved)} pin(s) could not be resolved to a repository (skipped):")
    for p in unresolved:
        print(f"  values.yaml:{p['line']}: {p['version']}")
    print()


def _print_unverifiable_pins(unverifiable: list[PinFailure]) -> None:
    """Print pins on an UNVERIFIABLE_HOSTS host or without a digest header; not a failure."""
    if not unverifiable:
        return
    print(
        f"{len(unverifiable)} image(s) on a registry this environment can't reach anonymously "
        f"(not counted as a failure — see lib.registry.UNVERIFIABLE_HOSTS):"
    )
    for repository, version, error, lines_str in unverifiable:
        print(f"  {repository}:{version}  {error}  (values.yaml:{lines_str})")
    print()


def _print_warning_and_stale_notes(acc: DigestCheckAccumulator):
    """Print the follow-up notes for sliding, stale and gone pins."""
    if acc.sliding_mismatches:
        print(
            f"{len(acc.sliding_mismatches)} sliding digest(s) above are routine, expected drift "
            f"(not counted as a failure) — still worth running fix-image-digests to refresh them."
        )
    if acc.mismatches:
        print(f"Run fix-image-digests to refresh the {len(acc.mismatches)} stale pinned digest(s) above.")
    if acc.digest_gone:
        print(
            f"{len(acc.digest_gone)} pinned digest(s) above are no longer resolvable upstream at all — "
            f"run fix-image-digests to re-pin against a digest that still exists."
        )


def _print_duplicate_pins(duplicates: dict[str, RepeatedPin]):
    """Print [DUPLICATE-PIN]: identical literal pins that should share a YAML anchor."""
    for repository, finding in duplicates.items():
        (version, _digest), pin_lines = finding["pins"][0]
        lines_str = ", ".join(str(n) for n in sorted(pin_lines))
        print(
            f"  [DUPLICATE-PIN] {repository}:{version}  hand-duplicated identically at "
            f"{len(pin_lines)} places (values.yaml:{lines_str}) instead of a shared YAML anchor "
            f'("&name" once, "*name" everywhere else) — the un-aliased cop{"y" if len(pin_lines) == 2 else "ies"} '
            f"can silently drift the next time this image is bumped elsewhere"
        )


def _print_drifted_pins(drifted: dict[str, RepeatedPin]):
    """Print [VERSION-DRIFT]: one repository pinned at different versions/digests."""
    for repository, finding in drifted.items():
        print(
            f"  [VERSION-DRIFT] {repository} pinned at {len(finding['pins'])} different versions/digests "
            f"across values.yaml:"
        )
        for (version, digest), pin_lines in finding["pins"]:
            lines_str = ", ".join(str(n) for n in pin_lines)
            print(f"      {version}@sha256:{digest}  (values.yaml:{lines_str})")


def _build_digest_check_result(
    acc: DigestCheckAccumulator,
    targets: dict[tuple[str, str], list[DigestPin]],
    duplicates: dict[str, RepeatedPin],
    drifted: dict[str, RepeatedPin],
    inconsistent: dict[str, RepeatedPin],
):
    """check_image_digests' (ok, detail); split out to limit its local-variable count."""
    detail = (
        f"{acc.matched}/{len(targets)} matched, {len(acc.sliding_mismatches)} sliding (warning), "
        f"{len(acc.mismatches)} stale, {len(acc.fetch_errors)} fetch error(s), "
        f"{len(acc.unverifiable)} unverifiable, "
        f"{len(acc.digest_gone)} pinned digest(s) gone, {len(acc.digest_check_errors)} digest fetch error(s), "
        f"{len(duplicates)} duplicate pin(s), {len(drifted)} version-drift finding(s)"
    )
    ok = not (acc.mismatches or acc.fetch_errors or acc.digest_gone or acc.digest_check_errors or inconsistent)
    return ok, detail


def check_image_digests(chart_dir: Path):
    """Report-only: compare every digest pin with its live upstream digest; fix with fix-image-digests.

    One request per unique (repository, version). A mismatch is "sliding"
    (warning) when git history shows the tag changed digest before, or else
    a more specific sibling tag has that digest (is_sliding_tag); otherwise
    it fails, since a release tag shouldn't change.

    Pins without a repository fall back to the subchart default, else are
    skipped. Fetch errors on UNVERIFIABLE_HOSTS never fail the check.
    Flagged pins are also checked for a gone digest. A repository pinned
    literally more than once fails as [DUPLICATE-PIN] or [VERSION-DRIFT].
    """
    values_path = chart_dir / "values.yaml"
    pins, targets = resolve_pin_targets(chart_dir)
    unresolved = [p for p in pins if not p["repository"]]

    print(
        f"Found {len(pins)} digest-pinned image(s), {len(targets)} unique image:tag to check "
        f"({len(unresolved)} unresolved, skipped)"
    )

    acc = DigestCheckAccumulator(0, [], [], [], [], [], [])
    sorted_targets = sorted(targets.items())
    for i, ((repository, version), group) in enumerate(sorted_targets, 1):
        ctx = _build_pin_context(chart_dir, values_path, repository, version, group)
        _process_pin(ctx, i, len(sorted_targets), acc)

    print()
    _print_unresolved_pins(unresolved)
    _print_unverifiable_pins(acc.unverifiable)
    _print_warning_and_stale_notes(acc)

    inconsistent = find_inconsistent_version_pins(pins)
    duplicates = {r: f for r, f in inconsistent.items() if f["kind"] == "duplicate"}
    drifted = {r: f for r, f in inconsistent.items() if f["kind"] == "drift"}
    _print_duplicate_pins(duplicates)
    _print_drifted_pins(drifted)

    return _build_digest_check_result(acc, targets, duplicates, drifted, inconsistent)
