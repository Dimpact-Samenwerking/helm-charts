"""Verifies every digest-pinned image in values.yaml still matches its live
upstream registry digest — report-only, never writes to values.yaml (see
fix-image-digests for that)."""
import re
import urllib.error
from datetime import datetime, timezone

from lib.chart import load_yaml, subchart_default_repository
from lib.registry import UNVERIFIABLE_HOSTS, is_sliding_tag, parse_repo, registry_tag_exists
from lib.repo_access_cache import cache_entry_is_fresh as repo_access_entry_is_fresh
from lib.repo_access_cache import cache_key as repo_access_cache_key
from lib.repo_access_cache import load_cache as load_repo_access_cache
from lib.repo_access_cache import save_cache as save_repo_access_cache

# One "tag: <version>@sha256:<digest>" pin per match, quoted or bare.
DIGEST_PIN_RE = re.compile(
    r'^(?P<indent>\s*)tag:\s*"?(?P<version>[\w][\w.\-]*)@sha256:(?P<digest>[0-9a-f]{64})"?\s*(?:#.*)?$'
)
# The SAME "tag:" pin shape DIGEST_PIN_RE matches, but with the "@sha256:
# <digest>" suffix made OPTIONAL rather than required — re-derived from
# DIGEST_PIN_RE itself (same indent/quote-handling) rather than written
# fresh, so the two can never subtly diverge on what counts as a valid
# "tag:" line. `digest` is None (never a match failure) for a bare,
# non-digest-pinned tag. Deliberately a SEPARATE regex/scanner (see
# scan_version_pins below), not a change to DIGEST_PIN_RE/scan_digest_pins
# themselves: this chart's own real digest-pinning convention (enforced
# for anything that actually gets deployed — see lib.digest_pinning_check)
# must stay exactly as strict as it already is for every caller that needs
# it (update-image-version/verify-image-version/show-image-baseline-
# version, and every upgrade_docs_baseline-driven doc-consistency check).
# Only verify-release-table-with-podiumd (via lib.image_version's own
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
    r'^(?P<indent>\s*)tag:\s*"?(?P<version>[\w][\w.\-]*)(?:@sha256:(?P<digest>[0-9a-f]{64}))?"?\s*(?:#.*)?$'
)
# An active (uncommented) sibling "repository:" key.
ACTIVE_REPO_RE = re.compile(
    r'^(?P<indent>\s*)repository:\s*"?(?P<repo>[\w][\w.\-]*(?:/[\w.\-]+)*)"?\s*(?:#.*)?$'
)
# An active (uncommented) sibling "registry:" key — some pins (e.g.
# redis-ha's opstree/redis images) split the host out of "repository:"
# into its own key, unlike the combined "repository: <host>/<path>" style
# used everywhere else in this file. podiumd.image (_helpers.tpl) renders
# both styles identically ("{{ if .registry }}{{ .registry }}/{{ end
# }}{{ .repository }}"), so this is purely stylistic — but resolve_pin_repo
# must still honor it, or a split-style pin gets looked up against the
# wrong (guessed) registry. See find_sibling_registry.
ACTIVE_REGISTRY_RE = re.compile(
    r'^(?P<indent>\s*)registry:\s*"?(?P<registry>[\w][\w.\-]*)"?\s*(?:#.*)?$'
)
# A commented-out "#repository: <value>" key, left as a hint for components
# whose real repository is overridden at the gemeente/deployment level.
COMMENTED_REPO_RE = re.compile(
    r'^\s*#\s*repository:\s*"?(?P<repo>[\w][\w.\-]*(?:/[\w.\-]+)*)"?\s*$'
)
# A one-line "# host/repo:tag[@sha256:...]" reference comment, placed above
# the "image:" block for the same override components. Tolerates a stray
# "@" right after the colon, seen on one existing comment in values.yaml.
REF_COMMENT_RE = re.compile(
    r'^\s*#\s*(?P<repo>[a-zA-Z0-9][\w.\-]*(?:/[\w.\-]+)*):@?[\w][\w.\-]*(?:@sha256:[0-9a-f]{64})?\s*$'
)


def find_sibling_registry(lines, tag_line_index, tag_indent):
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


def find_inconsistent_version_pins(pins):
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
    lib.image_version.image_basename) — a shared basename across
    different orgs/paths (docker.io/x/tool vs ghcr.io/y/tool) isn't the
    same image at all, so basename grouping would false-positive there.

    Returns {repository: {"kind": "duplicate"|"drift",
    "pins": [((version, digest), [line, ...]), ...]}} for every
    repository pinned literally in more than one place; a repository
    pinned only once (the common case) is omitted entirely."""
    by_repo = {}
    for p in pins:
        if not p["repository"]:
            continue
        by_repo.setdefault(p["repository"], []).append((p["version"], p["digest"], p["line"]))

    findings = {}
    for repo, entries in by_repo.items():
        if len(entries) < 2:
            continue
        pairs = {}
        for version, digest, line in entries:
            pairs.setdefault((version, digest), []).append(line)
        findings[repo] = {"kind": "duplicate" if len(pairs) == 1 else "drift", "pins": list(pairs.items())}
    return findings


def resolve_pin_repo(lines, tag_line_index, tag_indent):
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


def scan_digest_pins(lines):
    """Yield one record per "tag: <version>@sha256:<digest>" pin in
    values.yaml, with its resolved upstream repository. A single image (e.g.
    nginx-unprivileged) is typically pinned many times across the file."""
    pins = []
    for i, raw in enumerate(lines):
        m = DIGEST_PIN_RE.match(raw)
        if not m:
            continue
        indent = len(m.group("indent"))
        pins.append({
            "line": i + 1,
            "version": m.group("version"),
            "digest": m.group("digest"),
            "repository": resolve_pin_repo(lines, i, indent),
        })
    return pins


def scan_version_pins(lines):
    """The SAME shape scan_digest_pins returns, but for EVERY "tag:" pin
    (see VERSION_PIN_RE) whether or not it's digest-pinned — "digest" is
    None for a bare tag, never a reason to skip it. Exists solely for
    verify-release-table-with-podiumd (via lib.image_version's own
    *_any_tag functions): release-table.csv only ever records version
    strings, never digests, so a real, comparable version pin that simply
    isn't digest-pinned (yet, or by convention at an old release_table
    baseline) must still be found, not silently invisible the way
    scan_digest_pins' own digest-required scan would leave it. Every OTHER
    caller keeps using scan_digest_pins unchanged — this is strictly
    additive, never a replacement for the real digest-pinning guarantee
    those enforce."""
    pins = []
    for i, raw in enumerate(lines):
        m = VERSION_PIN_RE.match(raw)
        if not m:
            continue
        indent = len(m.group("indent"))
        pins.append({
            "line": i + 1,
            "version": m.group("version"),
            "digest": m.group("digest"),
            "repository": resolve_pin_repo(lines, i, indent),
        })
    return pins


def unique_digest_pin_targets(values_lines):
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
    targets = {}
    for p in pins:
        if p["repository"]:
            targets.setdefault((p["repository"], p["version"]), (p["digest"], p["line"]))
    return targets


def resolve_pin_targets(chart_dir):
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
    deps = load_yaml(chart_yaml_path).get("dependencies", []) if chart_yaml_path.is_file() else []
    subchart_cache = {}
    for p in pins:
        if not p["repository"]:
            p["repository"] = subchart_default_repository(chart_dir, lines, p["line"], deps, subchart_cache)

    targets = {}
    for p in pins:
        if p["repository"]:
            targets.setdefault((p["repository"], p["version"]), []).append(p)
    return pins, targets


_tag_exists_cache = {}


def cached_tag_exists(chart_dir, repository, host, repo_path, version, timeout=None):
    """Wrapper around lib.registry.registry_tag_exists for the tag-level
    lookup check_image_digests' own loop (below), find_sliding_pins, AND
    lib.repo_access.check_repo_access all make for the same pin — keyed
    on (repository, version), the same key resolve_pin_targets' own
    grouping already uses. "CVE diff" lists "Image digests" as a STEP_
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
       minute REPO_ACCESS_CACHE_TTL_MINUTES this relies on was already
       short by design, chosen for exactly this kind of live-value
       staleness tradeoff.)

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
    key = (repository, version)
    if key in _tag_exists_cache:
        return _tag_exists_cache[key]

    disk_key = repo_access_cache_key("registry", (host, repo_path, version))
    disk_cache = load_repo_access_cache(chart_dir)
    disk_entry = disk_cache.get(disk_key)
    if disk_entry and repo_access_entry_is_fresh(disk_entry) and "digest" in disk_entry:
        result = (True, disk_entry["digest"])
        _tag_exists_cache[key] = result
        return result

    # timeout kwarg only passed through when given, not as timeout=None --
    # every existing caller of registry_tag_exists mocks it with a plain
    # (host, repo, tag) callable (no timeout param at all), same
    # established convention as lib.registry._urlopen's own "only pass
    # timeout= when the caller asked for one".
    result = (registry_tag_exists(host, repo_path, version, timeout=timeout) if timeout is not None
              else registry_tag_exists(host, repo_path, version))
    _tag_exists_cache[key] = result

    exists, digest = result
    if exists:
        disk_cache[disk_key] = {
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "digest": digest,
        }
        save_repo_access_cache(chart_dir, disk_cache)

    return result


def find_sliding_pins(chart_dir):
    """[(repository, version, pinned_digest, digest)] for every unique
    digest pin whose live upstream digest has SLID (see check_image_
    digests' own docstring for the sliding-vs-genuine-drift
    distinction) — the exact same per-pin registry lookup (registry_
    tag_exists + is_sliding_tag) check_image_digests' own loop already
    performs, built on the same resolve_pin_targets(...) grouping,
    factored out here so lib.cve_diff_check.check_cve_diff can gather
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

    sliding = []
    for (repository, version), group in sorted(targets.items()):
        host, repo_path = parse_repo(repository)
        pinned_digest = group[0]["digest"]
        try:
            exists, digest = cached_tag_exists(chart_dir, repository, host, repo_path, version)
        except (urllib.error.URLError, OSError):
            continue
        if not exists or not digest or digest == f"sha256:{pinned_digest}":
            continue
        if is_sliding_tag(values_path, host, repo_path, version, digest):
            sliding.append((repository, version, pinned_digest, digest))
    return sliding


def check_image_digests(chart_dir):
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
    should never legitimately change once published. Sliding is now only
    a WARNING, not a failure — "expected" here really does mean routine,
    ongoing drift a floating base tag is supposed to have, not a stale
    pin that needs fixing before this repo's own content is trustworthy.
    A non-sliding mismatch (a component's own release tag changed digest,
    which should never legitimately happen) still FAILS. Either way, run
    fix-image-digests to refresh the pin — sliding or not, it always
    rewrites every stale pin it finds.

    A pin whose "tag:" has no resolvable "repository:" of its own in
    values.yaml (resolve_pin_repo) falls back to the same component's
    vendored subchart default (lib.chart.subchart_default_repository) —
    the repository Helm itself merges in at render time when podiumd
    doesn't override it. Still unresolved after that (dependency/.tgz
    missing, or the subchart doesn't default one there either) is skipped,
    same as before.

    A fetch error against a host in lib.registry.UNVERIFIABLE_HOSTS (one
    that rejects even an anonymous manifest read outright — confirmed not
    fixable by a better anonymous-token flow) is reported separately as
    unverifiable rather than a genuine FETCH-ERR, and never fails the
    check on its own — it can't succeed from an unprivileged environment
    regardless of whether the pin itself is correct.

    A SECOND, genuinely different question, checked for any pin whose tag
    came back sliding/mismatch/fetch-error/unverifiable-no-digest-header
    (never for a matched pin — its live digest already equals the pinned
    one, so it's trivially still there; never for a host already in
    UNVERIFIABLE_HOSTS — no point attempting what's already known to fail
    anonymously): is the EXACT digest values.yaml pins TODAY
    ("<repo>@sha256:<pinned_digest>") still resolvable on the registry AT
    ALL? Unlike a sliding/stale TAG (the tag now points somewhere else,
    but the image this repo actually deploys is still whatever's pinned),
    a registry that has garbage-collected/deleted that specific manifest
    means `helm install`/`upgrade` would fail outright right now — a real,
    hard failure, reported as [DIGEST-GONE] and FAILING regardless of
    whether the tag-level finding above it was only a warning. Reuses
    lib.registry.registry_tag_exists unchanged: its manifest URL accepts
    a digest string in exactly the same position a tag goes, so no new
    registry-layer code is needed, just a second call with
    "sha256:<pinned_digest>" instead of the version. A genuine network
    error while making THIS call (as opposed to a confirmed 404) is
    tracked and FAILS separately from an ordinary tag-check FETCH-ERR —
    two independent network calls per pin can each fail independently,
    and conflating their counts would make either one's own count
    misleading.

    Any repository pinned literally in more than one place in values.yaml
    (see find_inconsistent_version_pins) FAILS the check, one of two ways:
    a [DUPLICATE-PIN] (every occurrence agrees — should be a YAML alias to
    a shared anchor instead of hand-duplicated text, since nothing then
    stops the un-aliased copy from silently drifting on a future bump) or
    a [VERSION-DRIFT] (the occurrences disagree — different versions, or
    the same version pinned with a different digest, e.g. a sliding tag
    refreshed at one spot but not the other)."""
    values_path = chart_dir / "values.yaml"
    pins, targets = resolve_pin_targets(chart_dir)
    unresolved = [p for p in pins if not p["repository"]]

    print(f"Found {len(pins)} digest-pinned image(s), {len(targets)} unique image:tag to check "
          f"({len(unresolved)} unresolved, skipped)")

    matched = 0
    mismatches = []
    sliding_mismatches = []
    fetch_errors = []
    unverifiable = []
    digest_gone = []
    digest_check_errors = []

    sorted_targets = sorted(targets.items())
    for i, ((repository, version), group) in enumerate(sorted_targets, 1):
        host, repo_path = parse_repo(repository)
        pinned_digest = group[0]["digest"]
        lines_str = ", ".join(str(p["line"]) for p in group)

        # No per-run cache of its own here (unlike check_cves/check_image_
        # upgrades) — this always makes a real registry call the first
        # time THIS process sees a given pin, so it's worth announcing for
        # every single one, not just a slow subset. cached_tag_exists
        # still shares that one real call with find_sliding_pins, should
        # this same pin get asked about again later in the same run (e.g.
        # a --include=cve-diff invocation, which needs both).
        print(f"  [{i}/{len(sorted_targets)}] checking {host}/{repo_path}:{version}...", flush=True)

        digest, error = None, None
        for _attempt in range(2):
            try:
                exists, digest = cached_tag_exists(chart_dir, repository, host, repo_path, version)
                error = None if exists else "tag not found upstream"
                break
            except (urllib.error.URLError, OSError) as e:
                error = str(e)

        needs_digest_check = False

        if error and host in UNVERIFIABLE_HOSTS:
            unverifiable.append((repository, version, error, lines_str))
            print(f"  [UNVERIFIABLE] {host}/{repo_path}:{version}  {error}  (values.yaml:{lines_str})")
        elif error:
            fetch_errors.append((repository, version, error, lines_str))
            print(f"  [FETCH-ERR] {host}/{repo_path}:{version}  {error}  (values.yaml:{lines_str})")
            needs_digest_check = True
        elif digest and digest != f"sha256:{pinned_digest}":
            sliding = is_sliding_tag(values_path, host, repo_path, version, digest)
            if sliding:
                sliding_mismatches.append((repository, version, pinned_digest, digest, lines_str))
                print(f"  [SLIDING  ] {host}/{repo_path}:{version}  (known to drift — "
                      f"refresh with fix-image-digests)")
                print(f"      pinned:   sha256:{pinned_digest}")
                print(f"      upstream: {digest}")
                print(f"      lines:    values.yaml:{lines_str}")
            else:
                mismatches.append((repository, version, pinned_digest, digest, lines_str))
                print(f"  [MISMATCH ] {host}/{repo_path}:{version}")
                print(f"      pinned:   sha256:{pinned_digest}")
                print(f"      upstream: {digest}")
                print(f"      lines:    values.yaml:{lines_str}")
            needs_digest_check = True
        elif not digest:
            # Tag exists, but the manifest response carried no
            # Docker-Content-Digest header (some registries/media types, a
            # caching proxy that strips it) — we cannot confirm the pin, so
            # it must NOT be counted as matched. Same "couldn't verify"
            # bucket as an unreachable host (not a build failure), matching
            # update_image_version / check_basename_version's own
            # `if not exists or not digest` guard.
            reason = "registry returned no digest header"
            unverifiable.append((repository, version, reason, lines_str))
            print(f"  [UNVERIFIABLE] {host}/{repo_path}:{version}  {reason}  (values.yaml:{lines_str})")
            needs_digest_check = True
        else:
            matched += 1

        if needs_digest_check and host not in UNVERIFIABLE_HOSTS:
            digest_ref = f"sha256:{pinned_digest}"
            digest_exists, digest_error = None, None
            for _attempt in range(2):
                try:
                    digest_exists, _ = registry_tag_exists(host, repo_path, digest_ref)
                    digest_error = None
                    break
                except (urllib.error.URLError, OSError) as e:
                    digest_error = str(e)

            if digest_error:
                digest_check_errors.append((repository, version, digest_error, lines_str))
                print(f"  [FETCH-ERR] {host}/{repo_path}@{digest_ref}  {digest_error}  (while "
                      f"confirming the currently-pinned digest is still pullable, "
                      f"values.yaml:{lines_str})")
            elif not digest_exists:
                digest_gone.append((repository, version, pinned_digest, lines_str))
                print(f"  [DIGEST-GONE] {host}/{repo_path}@{digest_ref}  the EXACT digest "
                      f"values.yaml pins TODAY is no longer resolvable upstream at all — "
                      f"helm install/upgrade would fail outright right now "
                      f"(values.yaml:{lines_str})")

    print()
    if unresolved:
        print(f"{len(unresolved)} pin(s) could not be resolved to a repository (skipped):")
        for p in unresolved:
            print(f"  values.yaml:{p['line']}: {p['version']}")
        print()

    if unverifiable:
        print(f"{len(unverifiable)} image(s) on a registry this environment can't reach anonymously "
              f"(not counted as a failure — see lib.registry.UNVERIFIABLE_HOSTS):")
        for repository, version, error, lines_str in unverifiable:
            print(f"  {repository}:{version}  {error}  (values.yaml:{lines_str})")
        print()

    if sliding_mismatches:
        print(f"{len(sliding_mismatches)} sliding digest(s) above are routine, expected drift "
              f"(not counted as a failure) — still worth running fix-image-digests to refresh them.")
    if mismatches:
        print(f"Run fix-image-digests to refresh the {len(mismatches)} stale pinned digest(s) above.")
    if digest_gone:
        print(f"{len(digest_gone)} pinned digest(s) above are no longer resolvable upstream at all — "
              f"run fix-image-digests to re-pin against a digest that still exists.")

    inconsistent = find_inconsistent_version_pins(pins)
    duplicates = {r: f for r, f in inconsistent.items() if f["kind"] == "duplicate"}
    drifted = {r: f for r, f in inconsistent.items() if f["kind"] == "drift"}

    for repository, finding in duplicates.items():
        (version, digest), pin_lines = finding["pins"][0]
        lines_str = ", ".join(str(n) for n in sorted(pin_lines))
        print(f"  [DUPLICATE-PIN] {repository}:{version}  hand-duplicated identically at "
              f"{len(pin_lines)} places (values.yaml:{lines_str}) instead of a shared YAML anchor "
              f'("&name" once, "*name" everywhere else) — the un-aliased cop{"y" if len(pin_lines) == 2 else "ies"} '
              f"can silently drift the next time this image is bumped elsewhere")

    for repository, finding in drifted.items():
        print(f"  [VERSION-DRIFT] {repository} pinned at {len(finding['pins'])} different versions/digests "
              f"across values.yaml:")
        for (version, digest), pin_lines in finding["pins"]:
            lines_str = ", ".join(str(n) for n in pin_lines)
            print(f"      {version}@sha256:{digest}  (values.yaml:{lines_str})")

    detail = (f"{matched}/{len(targets)} matched, {len(sliding_mismatches)} sliding (warning), "
              f"{len(mismatches)} stale, {len(fetch_errors)} fetch error(s), "
              f"{len(unverifiable)} unverifiable, "
              f"{len(digest_gone)} pinned digest(s) gone, {len(digest_check_errors)} digest fetch error(s), "
              f"{len(duplicates)} duplicate pin(s), {len(drifted)} version-drift finding(s)")
    if mismatches or fetch_errors or digest_gone or digest_check_errors or inconsistent:
        return False, detail
    return True, detail
