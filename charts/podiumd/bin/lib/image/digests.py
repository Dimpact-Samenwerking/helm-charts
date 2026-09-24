"""Verifies every digest-pinned image in values.yaml still matches its live
upstream registry digest — report-only, never writes to values.yaml (see
fix-image-digests for that)."""

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

from lib.chart.chart_yaml import load_chart_dependencies
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

# One "tag: <version>@sha256:<digest>" pin per match, quoted or bare. The
# optional "&anchor" group tolerates a YAML anchor tag on the line's own
# value (e.g. "tag: &keycloakImageVersion \"26.7.3\"") — the same shape
# lib.chart.replace_scalar_value's own rewrite regex already handles on
# the write side; an *alias* reference ("tag: *keycloakImageVersion", no
# literal value at all) still can't match either regex below, and isn't
# meant to — there's nothing to read there.
DIGEST_PIN_RE = re.compile(
    r'^(?P<indent>\s*)tag:\s*(?:&\S+\s+)?"?(?P<version>[\w][\w.\-]*)@sha256:(?P<digest>[0-9a-f]{64})"?\s*(?:#.*)?$'
)
# The SAME "tag:" pin shape DIGEST_PIN_RE matches, but with the "@sha256:
# <digest>" suffix made OPTIONAL rather than required — re-derived from
# DIGEST_PIN_RE itself (same indent/quote-handling) rather than written
# fresh, so the two can never subtly diverge on what counts as a valid
# "tag:" line. `digest` is None (never a match failure) for a bare,
# non-digest-pinned tag. Deliberately a SEPARATE regex/scanner (see
# scan_version_pins below), not a change to DIGEST_PIN_RE/scan_digest_pins
# themselves: this chart's own real digest-pinning convention (enforced
# for anything that actually gets deployed — see lib.checks.digest_pinning)
# must stay exactly as strict as it already is for every caller that needs
# it (update-image-version/verify-image-version/show-image-baseline-
# version, and every upgrade_docs_baseline-driven doc-consistency check).
# Only verify-release-table-with-podiumd (via lib.image.version's own
# *_any_tag siblings) uses this one — release-table.csv itself has no
# concept of digests at all, so digest-pinning status was never something
# ITS OWN comparisons should have cared about; that script only ever
# inherited "digest required" as an accidental side effect of reusing
# scan_digest_pins, never a deliberate choice for its own purpose. Real
# case, confirmed live: podiumd-4.8.5 (this chart's own release_table
# baseline as of this writing) still had zaakbrug/pabc/ita pinned with
# bare, non-digest tags — invisible to DIGEST_PIN_RE, even though a real,
# comparable version string genuinely was there.
VERSION_PIN_RE = re.compile(
    r'^(?P<indent>\s*)tag:\s*(?:&\S+\s+)?"?(?P<version>[\w][\w.\-]*)(?:@sha256:(?P<digest>[0-9a-f]{64}))?"?\s*(?:#.*)?$'
)
# An active (uncommented) sibling "repository:" key. Same "&anchor"
# tolerance as DIGEST_PIN_RE/VERSION_PIN_RE above.
ACTIVE_REPO_RE = re.compile(
    r'^(?P<indent>\s*)repository:\s*(?:&\S+\s+)?"?(?P<repo>[\w][\w.\-]*(?:/[\w.\-]+)*)"?\s*(?:#.*)?$'
)
# An active (uncommented) sibling "registry:" key — some pins (e.g.
# redis-ha's opstree/redis images) split the host out of "repository:"
# into its own key, unlike the combined "repository: <host>/<path>" style
# used everywhere else in this file. podiumd.image (_helpers.tpl) renders
# both styles identically ("{{ if .registry }}{{ .registry }}/{{ end
# }}{{ .repository }}"), so this is purely stylistic — but resolve_pin_repo
# must still honor it, or a split-style pin gets looked up against the
# wrong (guessed) registry. See find_sibling_registry.
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
    """One digest-pinned "tag: <version>@sha256:<digest>" line of
    values.yaml (see scan_digest_pins); line is 1-based."""

    line: int
    version: str
    digest: str
    repository: str | None


class VersionPin(TypedDict):
    """One "tag:" line of values.yaml, digest-pinned or not (see
    scan_version_pins): digest is None for a bare tag."""

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


def find_sibling_registry(lines: list[str], tag_line_index: int, tag_indent: int):
    """The value of a sibling "registry:" key at the same indent as the
    "tag:" pin at tag_line_index, if present — e.g. redis-ha's split
    `registry: quay.io` / `repository: opstree/redis` style, as opposed to
    the single combined "repository: quay.io/opstree/redis" style used
    everywhere else in this file. Returns None if there's no such key
    (the common case)."""
    for i in range(tag_line_index - 1, max(tag_line_index - 15, -1), -1):
        raw = lines[i]
        if not raw.strip():
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        if indent < tag_indent:
            break
        m = ACTIVE_REGISTRY_RE.match(raw)
        if m and indent == tag_indent:
            return m.group("registry")
    return None


def find_inconsistent_version_pins(pins: list[DigestPin]) -> dict[str, RepeatedPin]:
    """Every repository pinned as a literal (non-alias) "tag:" in more than
    one place across values.yaml — always a real problem, just one of two
    different kinds:

    "duplicate" — every occurrence currently agrees on the exact same
    (version, digest). There's no legitimate reason two spots need to be
    hand-typed identically instead of one being a YAML alias ("*name") to
    the other's anchor ("&name") — confirmed by hand: curlimages/curl is
    defined once via "&curlImage" and reused via "*curlImage" in three
    places, but ALSO hand-duplicated verbatim at kiss.settings.elastic.
    indexTemplateImage, which isn't protected by that alias at all and
    can silently drift the next time the anchor is bumped without anyone
    remembering this spot exists.

    "drift" — the occurrences disagree: different versions, or the same
    version pinned with a different digest (e.g. a sliding tag refreshed
    at one spot but not the other, invisible to a version-only
    comparison). This COULD be a deliberate variant of the same
    repository (e.g. python:3.14-slim vs python:3.14-alpine share the
    exact repository "library/python", differing only in tag suffix) —
    but as of 2026-08-26 no repository in this chart is actually pinned
    at more than one version anywhere, so there's no real precedent this
    would break; a real future variant pin would need to fail loudly here
    too rather than let genuine drift slide through unnoticed.

    Grouped by the exact "repository:" string, not by basename (see
    lib.image.version.image_basename) — a shared basename across
    different orgs/paths (docker.io/x/tool vs ghcr.io/y/tool) isn't the
    same image at all, so basename grouping would false-positive there.

    Returns {repository: {"kind": "duplicate"|"drift",
    "pins": [((version, digest), [line, ...]), ...]}} for every
    repository pinned literally in more than one place; a repository
    pinned only once (the common case) is omitted entirely."""
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
    """Resolve the upstream repository for a "tag:" pin at tag_line_index.
    Most pins have an active sibling "repository:" key. A minority of
    components (e.g. office_converter, opa, solr-operator) deliberately
    comment their "repository:" out so gemeente-level ACR-mirror overrides
    take precedence — for those, fall back to the "# host/repo:tag" style
    reference comment placed above the "image:" block, or a commented-out
    "#repository: <value>" key at the same indent. A sibling "registry:"
    key (see find_sibling_registry) is prefixed on when present, so a
    split-style pin resolves to the same host/path a combined-style pin
    would."""
    for i in range(tag_line_index - 1, max(tag_line_index - 15, -1), -1):
        raw = lines[i]
        if not raw.strip():
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        if indent < tag_indent:
            break
        m = ACTIVE_REPO_RE.match(raw)
        if m and indent == tag_indent:
            repo = m.group("repo")
            registry = find_sibling_registry(lines, tag_line_index, tag_indent)
            return f"{registry}/{repo}" if registry else repo
    for i in range(tag_line_index - 1, max(tag_line_index - 6, -1), -1):
        m = REF_COMMENT_RE.match(lines[i])
        if m:
            return m.group("repo")
    for i in range(tag_line_index - 1, max(tag_line_index - 6, -1), -1):
        m = COMMENTED_REPO_RE.match(lines[i])
        if m:
            return m.group("repo")
    return None


def scan_digest_pins(lines: list[str]) -> list[DigestPin]:
    """Yield one record per "tag: <version>@sha256:<digest>" pin in
    values.yaml, with its resolved upstream repository. A single image (e.g.
    nginx-unprivileged) is typically pinned many times across the file."""
    pins: list[DigestPin] = []
    for i, raw in enumerate(lines):
        m = DIGEST_PIN_RE.match(raw)
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


def scan_version_pins(lines: list[str]) -> list[VersionPin]:
    """The SAME shape scan_digest_pins returns, but for EVERY "tag:" pin
    (see VERSION_PIN_RE) whether or not it's digest-pinned — "digest" is
    None for a bare tag, never a reason to skip it. Exists solely for
    verify-release-table-with-podiumd (via lib.image.version's own
    *_any_tag functions): release-table.csv only ever records version
    strings, never digests, so a real, comparable version pin that simply
    isn't digest-pinned (yet, or by convention at an old release_table
    baseline) must still be found, not silently invisible the way
    scan_digest_pins' own digest-required scan would leave it. Every OTHER
    caller keeps using scan_digest_pins unchanged — this is strictly
    additive, never a replacement for the real digest-pinning guarantee
    those enforce."""
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
    """{(repository, version): (digest, line)} for the FIRST occurrence
    of every digest pin whose repository resolves from values.yaml
    ITSELF (an active sibling "repository:"/"registry:" pair, or one of
    the comment-based fallbacks resolve_pin_repo already tries) — no
    vendored-subchart-default fallback here (see resolve_pin_targets,
    below, for the richer version check_image_digests itself needs,
    which DOES apply that fallback). Shared by check_image_upgrades,
    check_cves, and check_cve_diff — all three only ever need this
    simpler resolution, so factored out here once rather than each
    hand-rolling the same "first (digest, line) wins per unique
    (repository, version)" grouping a third and fourth time."""
    pins = scan_digest_pins(values_lines)
    targets: dict[tuple[str, str], tuple[str, int]] = {}
    for p in pins:
        if p["repository"]:
            targets.setdefault((p["repository"], p["version"]), (p["digest"], p["line"]))
    return targets


def resolve_pin_targets(chart_dir: Path):
    """pins (repository resolved via resolve_pin_repo, falling back to
    the vendored subchart's own default via subchart_default_repository
    when values.yaml has no active "repository:" of its own — the
    richer resolution check_image_digests' own loop needs, unlike
    unique_digest_pin_targets above) and the {(repository, version):
    [pin, ...]} grouping built from them. Factored out of check_image_
    digests' own setup so find_sliding_pins (below) can reuse the exact
    same subchart-default-fallback resolution rather than re-deriving
    it a second time."""
    values_path = chart_dir / "values.yaml"
    lines = values_path.read_text(encoding="utf-8").splitlines()
    pins = scan_digest_pins(lines)

    chart_yaml_path = chart_dir / "Chart.yaml"
    deps = load_chart_dependencies(chart_yaml_path) if chart_yaml_path.is_file() else []
    subchart_cache = {}
    for p in pins:
        if not p["repository"]:
            p["repository"] = subchart_default_repository(chart_dir, lines, p["line"], deps, subchart_cache)

    targets = {}
    for p in pins:
        if p["repository"]:
            targets.setdefault((p["repository"], p["version"]), []).append(p)
    return pins, targets


_tag_exists_cache: dict[tuple[str, str], tuple[bool, str | None]] = {}


def clear_tag_exists_cache() -> None:
    """Empty cached_tag_exists' in-process tier; the disk cache stays."""
    _tag_exists_cache.clear()


def cached_tag_exists(
    chart_dir: Path, repository: str, version: str, timeout: float | None = None
) -> tuple[bool, str | None]:
    """Wrapper around lib.registry.registry_tag_exists for the tag-level
    lookup check_image_digests' own loop (below), find_sliding_pins, AND
    lib.repo_access.check_repo_access all make for the same pin — keyed
    on (repository, version), the same key resolve_pin_targets' own
    grouping already uses. host/repo_path are re-derived here via
    parse_repo(repository) rather than threaded in by every caller — all
    of them already have (or can trivially build) a "host/repo_path"
    shaped repository string, so passing both forms in was pure
    redundancy. "CVE diff" lists "Image digests" as a STEP_
    PREREQUISITES entry specifically so charts/*.tgz is vendored first;
    without this, a --include=cve-diff run would make check_image_
    digests' own loop and check_cve_diff's own gather_candidates (via
    find_sliding_pins) each independently re-query the registry for
    every unique pin in the SAME process — doubling real network cost
    for no reason, same class of redundancy render_chart's own
    in-process cache already fixed for `helm template`. check_repo_
    access's own preflight shares the exact same disk-persisted store
    (see below), so a combined run (e.g. --include=repo-access,image-
    digests) makes ONE registry pass for the shared pin set, not two.

    timeout (seconds) is threaded straight through to the real
    registry_tag_exists call on a miss — check_repo_access's own reason
    for existing is a FAST, bounded preflight (see that module's own
    docstring), so it passes one; check_image_digests/find_sliding_pins
    don't, same as before this parameter existed.

    Two tiers, checked in order:
    1. An in-process dict (_tag_exists_cache) — the fastest path, avoids
       even a disk read for a pin already seen this process.
    2. lib.repo_access_cache's own disk-persisted, TTL-based store
       (<repo-root>/.cache/repo-access-cache.json) — the EXACT same
       cache_key/load_cache/save_cache/cache_entry_is_fresh check_repo_
       access itself uses, so a fresh entry either one writes is
       directly usable by the other, byte-for-byte, no format
       translation. (repo_access_cache's own docstring used to say this
       cache was "deliberately NOT shared" with anything needing a
       digest, since it only ever recorded a bare reachability bool —
       that's now out of date: this function extends its OWN entries
       with a "digest" field precisely so it CAN be shared. The 30-
       minute default repo_access.cache_ttl_minutes (lib.settings) this
       relies on was already short by design, chosen for exactly this
       kind of live-value staleness tradeoff.)

    On a genuine miss (both tiers), makes the real registry_tag_exists
    call. A "not found" result is cached in-process only, matching
    _tag_exists_cache's own existing behavior — but NOT persisted to
    disk, matching repo_access_cache's own established "only ever cache
    a SUCCESS" policy (a 404 might be a transient rate-limit response;
    perpetuating that past whatever caused it, across separate runs, is
    exactly what that policy already exists to avoid — see that
    module's own docstring). Only a found tag (exists=True) is written
    to disk, alongside its digest.

    An exception is never cached at either tier — it propagates
    straight through, so check_image_digests' own retry-on-transient-
    network-error loop still genuinely retries over the network rather
    than replaying a cached failure."""
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

    # timeout kwarg only passed through when given, not as timeout=None --
    # every existing caller of registry_tag_exists mocks it with a plain
    # (host, repo, tag) callable (no timeout param at all), same
    # established convention as lib.registry._urlopen's own "only pass
    # timeout= when the caller asked for one".
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
    """[(repository, version, pinned_digest, digest)] for every unique
    digest pin whose live upstream digest has SLID (see check_image_
    digests' own docstring for the sliding-vs-genuine-drift
    distinction) — the exact same per-pin registry lookup (registry_
    tag_exists + is_sliding_tag) check_image_digests' own loop already
    performs, built on the same resolve_pin_targets(...) grouping,
    factored out here so lib.checks.cve_diff.check_cve_diff can gather
    its own "digest has slid" scan candidates without re-deriving that
    lookup. A genuine (non-sliding) MISMATCH, a fetch error, or an
    unverifiable pin is NOT returned here — check_image_digests remains
    the one authoritative place those get reported; this function
    exists solely to answer "which pins have a slid digest" for a
    caller that doesn't care about the rest.

    Shares cached_tag_exists' own in-process memoization with check_
    image_digests' loop (see that function's own docstring) — whichever
    of the two runs first in a given verify-podiumd invocation pays the
    real registry cost per pin, the other gets a free hit. Silent either
    way — no per-pin progress printed here; check_image_digests' own run
    already announces each one."""
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
    """repository/host/repo_path/version for one pin being checked —
    host/repo_path are parse_repo(repository)'s own split, bundled here
    once so every helper below shares it instead of re-parsing."""

    repository: str
    host: str
    repo_path: str
    version: str


@dataclass
class PinCheckContext:
    """One pin's full per-iteration state, threaded through
    _resolve_pin_tag_status/_classify_pin_tag_result/_confirm_pinned_
    digest_still_resolvable — built once per pin by _build_pin_context."""

    chart_dir: Path
    values_path: Path
    pinned_digest: str
    lines_str: str
    loc: PinLocation


@dataclass
class DigestCheckAccumulator:
    """matched count + one list per outcome kind, mutated in place by
    _process_pin across check_image_digests' own per-pin loop, then read
    back afterward for the summary prints and the final detail string."""

    matched: int
    mismatches: list
    sliding_mismatches: list
    fetch_errors: list
    unverifiable: list
    digest_gone: list
    digest_check_errors: list


ResultT = TypeVar("ResultT")


def _call_with_retry(fn: Callable[[], ResultT]) -> tuple[ResultT | None, str | None]:
    """Call fn() up to twice, retried only on a transient network error
    (never on a clean, non-exception result) — the same two-attempt shape
    both registry lookups below need. Returns (result, error): result is
    None only when both attempts raised, in which case error is the
    second attempt's message."""
    result, error = None, None
    for _attempt in range(2):
        try:
            result = fn()
            error = None
            break
        except (urllib.error.URLError, OSError) as e:
            error = str(e)
    return (result, None) if error is None else (None, error)


def _build_pin_context(chart_dir: Path, values_path: Path, repository: str, version: str, group: list):
    """Resolve host/repo_path and the shared pinned_digest/lines_str for
    one (repository, version) target's pin group, bundled into the
    context every per-pin helper below needs."""
    host, repo_path = parse_repo(repository)
    pinned_digest = group[0]["digest"]
    lines_str = ", ".join(str(p["line"]) for p in group)
    loc = PinLocation(repository, host, repo_path, version)
    return PinCheckContext(chart_dir, values_path, pinned_digest, lines_str, loc)


def _resolve_pin_tag_status(ctx: PinCheckContext):
    """The tag-level lookup for one pin: cached_tag_exists, retried once
    on a transient network error. Returns (digest, error) — error is
    "tag not found upstream" for a clean 404, never None just because
    the tag wasn't found."""
    result, error = _call_with_retry(lambda: cached_tag_exists(ctx.chart_dir, ctx.loc.repository, ctx.loc.version))
    if result is None:
        return None, error
    exists, digest = result
    return digest, (None if exists else "tag not found upstream")


def _classify_pin_tag_result(ctx: PinCheckContext, digest: str | None, error: str | None, acc: DigestCheckAccumulator):
    """The four possible outcomes for one pin's tag-level lookup —
    unverifiable host, fetch error, mismatch (sliding or not), no digest
    header, or matched — each printed and recorded on acc. Returns
    whether the SECOND (digest-still-resolvable) check is warranted."""
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
        # Tag exists, but the manifest response carried no
        # Docker-Content-Digest header (some registries/media types, a
        # caching proxy that strips it) — we cannot confirm the pin, so
        # it must NOT be counted as matched. Same "couldn't verify"
        # bucket as an unreachable host (not a build failure), matching
        # update_image_version / check_basename_version's own
        # `if not exists or not digest` guard.
        reason = "registry returned no digest header"
        acc.unverifiable.append((repository, version, reason, ctx.lines_str))
        print(f"  [UNVERIFIABLE] {host}/{repo_path}:{version}  {reason}  (values.yaml:{ctx.lines_str})")
        return True
    acc.matched += 1
    return False


def _confirm_pinned_digest_still_resolvable(ctx: PinCheckContext, acc: DigestCheckAccumulator):
    """The SECOND check for a pin already flagged by _classify_pin_tag_
    result (never for a matched pin, never for a host already in
    UNVERIFIABLE_HOSTS): is the EXACT digest values.yaml pins TODAY still
    resolvable upstream at all — a registry that garbage-collected that
    manifest means `helm install`/`upgrade` would fail outright right
    now, reported as [DIGEST-GONE], regardless of whether the tag-level
    finding above it was only a warning."""
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
    """One pin's full check: announce it, resolve its tag-level status,
    classify the result, then run the digest-still-resolvable check when
    warranted. No per-run cache of its own here (unlike check_cves/
    check_image_upgrades) — this always makes a real registry call the
    first time THIS process sees a given pin, so it's worth announcing
    for every single one, not just a slow subset."""
    print(f"  [{i}/{total}] checking {ctx.loc.host}/{ctx.loc.repo_path}:{ctx.loc.version}...", flush=True)
    digest, error = _resolve_pin_tag_status(ctx)
    needs_digest_check = _classify_pin_tag_result(ctx, digest, error, acc)
    if needs_digest_check and ctx.loc.host not in UNVERIFIABLE_HOSTS:
        _confirm_pinned_digest_still_resolvable(ctx, acc)


def _print_unresolved_pins(unresolved: list[DigestPin]):
    """Every pin whose "tag:" has no resolvable "repository:" (see
    resolve_pin_repo/resolve_pin_targets) — skipped, not a failure."""
    if not unresolved:
        return
    print(f"{len(unresolved)} pin(s) could not be resolved to a repository (skipped):")
    for p in unresolved:
        print(f"  values.yaml:{p['line']}: {p['version']}")
    print()


def _print_unverifiable_pins(unverifiable: list):
    """Every pin on a host lib.registry.UNVERIFIABLE_HOSTS excuses, or
    whose manifest carried no digest header — not counted as a failure."""
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
    """The three one-line follow-up notes for sliding/stale/gone pins
    already printed in detail by _classify_pin_tag_result/_confirm_
    pinned_digest_still_resolvable above."""
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
    """[DUPLICATE-PIN] — a repository hand-duplicated identically in more
    than one place instead of a shared YAML anchor (see
    find_inconsistent_version_pins)."""
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
    """[VERSION-DRIFT] — a repository pinned at genuinely different
    versions/digests across values.yaml (see find_inconsistent_version_
    pins)."""
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
    targets: dict,
    duplicates: dict[str, RepeatedPin],
    drifted: dict[str, RepeatedPin],
    inconsistent: dict[str, RepeatedPin],
):
    """The final (ok, detail) pair check_image_digests returns, built from
    the accumulator plus the inconsistent-pin groupings — factored out
    solely to keep check_image_digests' own local-variable count down."""
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
    """Report-only: verify every digest-pinned image in values.yaml against
    its live upstream registry digest, to catch pins that are stale (tag
    unchanged, but upstream re-published it with new base/security layers).
    One network request per unique (repository, version) pair. Never writes
    to values.yaml — use fix-image-digests to fix confirmed-stale pins.

    A mismatch is classified sliding — expected drift, e.g. a floating
    base-image tag republished with new security patches — when this
    repo's own git history shows the tag has changed digest before, or
    (only if that's inconclusive) the registry currently has a more
    specific sibling tag at the same digest; see lib.registry.
    is_sliding_tag. Otherwise it's a component's own release tag, which
    should never legitimately change once published. Sliding is only a
    WARNING, not a failure. A non-sliding mismatch still FAILS. Either
    way, run fix-image-digests to refresh the pin.

    A pin whose "tag:" has no resolvable "repository:" of its own in
    values.yaml (resolve_pin_repo) falls back to the same component's
    vendored subchart default (lib.chart.subchart_default_repository).
    Still unresolved after that is skipped, same as before.

    A fetch error against a host in lib.registry.UNVERIFIABLE_HOSTS is
    reported separately as unverifiable, and never fails the check on its
    own — it can't succeed from an unprivileged environment regardless of
    whether the pin itself is correct.

    A SECOND, genuinely different question, checked for any pin whose tag
    came back sliding/mismatch/fetch-error/unverifiable-no-digest-header:
    is the EXACT digest values.yaml pins TODAY still resolvable on the
    registry at all? See _confirm_pinned_digest_still_resolvable.

    Any repository pinned literally in more than one place in values.yaml
    (see find_inconsistent_version_pins) FAILS the check, one of two ways:
    a [DUPLICATE-PIN] or a [VERSION-DRIFT] — see _print_duplicate_pins/
    _print_drifted_pins."""
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
