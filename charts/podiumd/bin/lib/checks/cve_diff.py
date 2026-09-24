"""Report-only check: for every image check_image_upgrades flagged with a
newer tag published, or check_image_digests flagged with a slid digest,
scan BOTH the currently-pinned image and the proposed replacement with
trivy (lib.checks.cve.run_trivy) and report the per-severity CVE SET
DIFFERENCE — which CVEs the proposed image closes (present now, absent
after) and which it newly introduces (absent now, present after). An
upgrade/re-pin decision informed by real security data, not just "a newer
tag/digest exists" (which lib.image.upgrade_check/lib.image.digests
already report on their own, with no opinion on whether it actually fixes
anything).

Deliberately a SEPARATE step from both of those (cheap, network-only, no
docker) and from check_cves itself (which scans every currently-pinned
image once, not a proposed replacement) — bolting a second per-candidate
docker+trivy cost onto a cheap step would recreate the exact cost-tier
mismatch this repo already found and fixed once for check_digest_pinning/
check_shared_image_usage (see lib.checks.digest_pinning's own module
docstring). Cost here is still bounded: only images with an ACTUAL
flagged upgrade or slide get a second scan, not every pinned image, so
this runs by default like every other step — no separate opt-in flag,
unlike check_cves' own --detail-cve-check.

Never fails, same "a triage decision for a human, not a chart-correctness
fact" precedent check_cves itself already established — a proposed image
introducing a new CRITICAL is worth knowing before bumping, not a reason
to make verify-podiumd itself red.

Reported split into the same own/partner-vendor/other-vendor buckets as
check_yamllint/check_kubeconform/check_shellcheck/check_kube_score/
check_cves — every candidate is classified via the exact same lib.
checks.cve machinery those already use (render-based "# Source:"
attribution first, falling back to a values.yaml top-level-key heuristic
for a component not present in the render at all — see
classify_candidates), reusing whatever render check_image_upgrades'
STEP_PREREQUISITES already produced rather than triggering a second real
`helm template`. Same as check_cves' own explicit convention: ALL THREE
buckets get identical treatment here too — full per-candidate scan+diff
output, own numbering, own closed/introduced totals — no aggregate-only
rollup for other-vendor (check_image_upgrades itself used to have exactly
that other-vendor aggregate-only shortcut and was fixed to drop it, for
the same reason). Unlike check_image_upgrades' own print_upgradable,
though, a candidate's printed line never grows a vendor-label suffix here
— bucket headers alone are enough context, and this module's per-
candidate line format is otherwise unchanged.

Candidates, gathered from two independent sources:
- "upgrade" — every unique digest pin (lib.image.digests.
  unique_digest_pin_targets, the same simple "no subchart-default
  fallback" resolution check_image_upgrades/check_cves already use) with
  a fresh lib.image.upgrade_cache entry showing a newer tag than the one
  currently pinned. current_ref is the plain pinned tag
  ("host/repo:version"); proposed_ref is that same repo at the newer tag.
  Reading image_upgrade_cache read-only here (same as check_cves' own
  "upgradable to X" annotation) is why "CVE diff" lists "Image upgrades"
  as a STEP_PREREQUISITES entry — a bare --include=cve-diff still needs
  that cache freshly populated first.
- "sliding digest" — every pin lib.image.digests.find_sliding_pins
  reports (the exact same registry lookup check_image_digests' own loop
  uses, factored out there so it isn't re-derived here — see that
  function's own docstring). current_ref MUST be digest-pinned
  ("repo@sha256:<pinned_digest>"), never the bare tag: the tag alone
  would now resolve to the NEW upstream digest, not what's actually
  pinned in values.yaml. proposed_ref is the same repo at the new
  upstream digest — deliberately digest-pinned too (not the bare tag),
  so this scan is reproducible regardless of whatever the tag resolves
  to by the time this step actually runs.

The two sources are independent and never deduplicated against each
other: a pin that happens to be BOTH sliding AND upgradable is reported
twice, once under each heading — a rare enough overlap in practice that
merging the two into one combined diff isn't worth the added complexity
it would take to do correctly.

Caching: BOTH sides of each candidate scan via lib.checks.cve.scan_cached
— the SAME shared "check the digest-keyed cve-scan-cache.json, report a
cache hit or announce a fresh scan, run trivy if needed, cache the
result" primitive check_cves' own per-image loop uses, rather than a
second, separately hand-rolled version of that same logic living here.
But the two sides, and the two candidate KINDS, get there differently:
- The CURRENT side is always cache-eligible immediately: its digest is
  already known from values.yaml, and check_cves (which runs
  immediately before this step in the default pipeline) already scanned
  every currently-pinned image, so this side is typically a free cache
  hit, not a second docker pull.
- A "sliding digest" candidate's PROPOSED side is ALSO free: find_
  sliding_pins already resolved the new upstream digest itself (a
  registry call check_image_digests' own work already made, not a new
  one this module triggers) — see gather_candidates' own
  "proposed_digest" field.
- An "upgrade" candidate's PROPOSED side is a bare TAG (lib.image.
  upgrade_check never records the digest, only the tag string) —
  its digest genuinely isn't known ahead of time, so caching it costs
  ONE extra registry_tag_exists manifest lookup (a cheap tag->digest
  resolve, NOT a docker pull) before the scan. If that resolve call
  itself fails, this candidate's proposed side just falls back to an
  uncached run_trivy — never treated as a scan failure on its own, the
  same tolerance the tag-check that produced the candidate in the first
  place already has for its own failed lookups."""

import urllib.error

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from typing import TypedDict

from lib.checks.cve import SEVERITY_ORDER
from lib.checks.cve import CacheSession
from lib.checks.cve import ScanTarget
from lib.checks.cve import Vulnerability
from lib.checks.cve import bucket_of
from lib.checks.cve import classify_by_key
from lib.checks.cve import dependency_names
from lib.checks.cve import high_findings_by_package
from lib.checks.cve import open_cache_session
from lib.checks.cve import print_bucket_header
from lib.checks.cve import print_package_line
from lib.checks.cve import render_image_labels
from lib.checks.cve import save_cache
from lib.checks.cve import scan_cached
from lib.checks.cve import severity_label
from lib.checks.cve import top_level_key_for_line
from lib.image.digests import find_sliding_pins
from lib.image.digests import unique_digest_pin_targets
from lib.image.upgrade_cache import cache_entry_is_fresh as upgrade_entry_is_fresh
from lib.image.upgrade_cache import cache_key as upgrade_cache_key
from lib.image.upgrade_cache import load_cache as load_upgrade_cache
from lib.registry import parse_repo
from lib.registry import registry_tag_exists
from lib.render_scope import friendly_vendor_charts
from lib.render_scope import render_chart
from lib.settings import cve_high_severity_levels
from lib.settings import cve_max_cves_per_package_before_summarizing
from lib.settings import cve_scan_cache_ttl_days
from lib.settings import image_upgrade_tag_check_cache_ttl_days


def _vuln_key(v: Vulnerability):
    return (v["VulnerabilityID"], v["PkgName"])


def diff_vulns(current_vulns: list[Vulnerability], proposed_vulns: list[Vulnerability]):
    """(closed, introduced) — lists of vuln dicts (same shape lib.
    checks.cve.run_trivy returns) present in exactly one side, keyed by
    the exact (VulnerabilityID, PkgName) pair. An EXACT set difference,
    never a naive per-severity count subtraction — that would hide e.g.
    "5 closed, 3 newly introduced" behind a misleading "net -2"."""
    current_by_key = {_vuln_key(v): v for v in current_vulns}
    proposed_by_key = {_vuln_key(v): v for v in proposed_vulns}
    closed = [v for key, v in current_by_key.items() if key not in proposed_by_key]
    introduced = [v for key, v in proposed_by_key.items() if key not in current_by_key]
    return closed, introduced


def _bare_digest(digest_ref: str):
    """ "sha256:<hex>" -> "<hex>" — lib.checks.cve.cache_key expects the
    bare hex digest (it prepends "sha256:" itself), but every digest this
    module gets handed back (find_sliding_pins, registry_tag_exists) has
    the full "sha256:" prefix already on it."""
    prefix = "sha256:"
    return digest_ref.removeprefix(prefix)


class DiffCandidate(TypedDict):
    """One image whose CVEs are diffed (see gather_candidates): "upgrade"
    to a newer tag, or a "sliding digest" whose tag moved upstream.
    proposed_digest is None until an upgrade's digest is resolved; line
    is the pin's values.yaml line, None when it can't be located."""

    kind: Literal["upgrade", "sliding digest"]
    repository: str
    version: str
    current_ref: str
    current_digest: str
    proposed_label: str
    proposed_ref: str
    proposed_digest: str | None
    line: int | None


class ClassifiedCandidate(DiffCandidate):
    """A DiffCandidate with its report bucket ("own", "partner", "other";
    see classify_candidates)."""

    bucket: str


# One report bucket as (bucket key, title, its candidates); see _partition_by_bucket.
CandidateBucket = tuple[str, str, list[ClassifiedCandidate]]


def gather_candidates(chart_dir: Path) -> list[DiffCandidate]:
    """[{"kind", "repository", "version", "current_ref", "current_digest",
    "proposed_label", "proposed_ref", "proposed_digest"}] — see this
    module's own docstring for exactly what each of the two candidate
    sources means and why each ref is built the way it is.

    "proposed_digest" is the one field that genuinely differs by kind:
    a "sliding digest" candidate's new upstream digest is already known
    (find_sliding_pins' own registry lookup resolved it), set here
    directly, no extra call. An "upgrade" candidate's proposed side is
    only ever a bare TAG (lib.image.upgrade_check never records a
    digest) — left None here, resolved lazily by _scan_proposed only if
    the candidate actually needs scanning."""
    values_path = chart_dir / "values.yaml"
    values_lines = values_path.read_text(encoding="utf-8").splitlines()
    targets = unique_digest_pin_targets(values_lines)

    upgrade_cache = load_upgrade_cache(chart_dir)
    upgrade_ttl_days = image_upgrade_tag_check_cache_ttl_days(chart_dir)
    candidates: list[DiffCandidate] = []
    for (repository, version), (digest, line) in sorted(targets.items()):
        entry = upgrade_cache.get(upgrade_cache_key(repository, version))
        if entry and upgrade_entry_is_fresh(entry, upgrade_ttl_days) and entry["newest"] != version:
            host, repo_path = parse_repo(repository)
            candidates.append(
                {
                    "kind": "upgrade",
                    "repository": repository,
                    "version": version,
                    "current_ref": f"{host}/{repo_path}:{version}",
                    "current_digest": digest,
                    "proposed_label": entry["newest"],
                    "proposed_ref": f"{host}/{repo_path}:{entry['newest']}",
                    "proposed_digest": None,
                    "line": line,
                }
            )

    for repository, version, pinned_digest, digest in find_sliding_pins(chart_dir):
        candidates.append(
            {
                "kind": "sliding digest",
                "repository": repository,
                "version": version,
                "current_ref": f"{repository}@sha256:{pinned_digest}",
                "current_digest": pinned_digest,
                "proposed_label": digest,
                "proposed_ref": f"{repository}@{digest}",
                "proposed_digest": _bare_digest(digest),
                "line": targets.get((repository, version), (None, None))[1],
            }
        )

    return candidates


@dataclass
class DiffContext:
    """chart_dir/cache/scan_errors/detail/ttl_days/high_severities/
    package_cve_list_threshold — check_cve_diff's own per-run inputs,
    identical across all three _process_bucket calls in one run (only
    `title`/`bucket_candidates` differ per bucket) — same idea as lib.
    checks.cve's own ScanContext/ReportSettings, bundled here so
    _process_bucket/_scan_current/_scan_proposed each take this one
    object instead of a handful of positional params. See
    _build_diff_context, which builds one of these once per run."""

    chart_dir: Path
    cache: CacheSession
    scan_errors: list[str]
    detail: bool
    ttl_days: int
    high_severities: set[str]
    package_cve_list_threshold: int


def _scan_current(context: DiffContext, candidate: DiffCandidate):
    """The CURRENT side of one candidate — always cache-eligible, its
    pinned digest is already known from values.yaml, a free hit whenever
    check_cves already scanned this exact digest (both route through the
    same lib.checks.cve.scan_cached — see its own docstring)."""
    vulns, _ = scan_cached(
        context.chart_dir,
        ScanTarget(candidate["repository"], candidate["current_digest"], candidate["current_ref"]),
        context.cache,
        context.ttl_days,
        label="current",
    )
    return vulns


def _scan_proposed(context: DiffContext, candidate: DiffCandidate):
    """The PROPOSED side of one candidate. A "sliding digest" candidate
    already carries its own resolved digest (see gather_candidates) — no
    extra call needed, straight to scan_cached. An "upgrade" candidate's
    own proposed_ref is a bare tag — resolve its digest first via ONE
    cheap registry_tag_exists manifest lookup (not a docker pull) so it
    can join the same cache. If that resolve call itself fails/errors,
    fall back to an uncached scan (digest=None) rather than treating the
    whole candidate as a failure — the tag-check that produced this
    candidate in the first place already tolerates the same kind of
    lookup failure without giving up on the candidate outright."""
    digest = candidate["proposed_digest"]
    if digest is None:
        host, repo_path = parse_repo(candidate["repository"])
        try:
            exists, resolved = registry_tag_exists(host, repo_path, candidate["proposed_label"])
            if exists and resolved:
                digest = _bare_digest(resolved)
        except (urllib.error.URLError, OSError):
            digest = None

    vulns, _ = scan_cached(
        context.chart_dir,
        ScanTarget(candidate["repository"], digest, candidate["proposed_ref"]),
        context.cache,
        context.ttl_days,
        label="proposed",
    )
    return vulns


def _severity_counts(vulns: list[Vulnerability]):
    counts = Counter(v["Severity"] for v in vulns)
    return ", ".join(f"{counts[s]} {severity_label(s)}" for s in SEVERITY_ORDER if counts.get(s))


def _print_direction(
    label: str, vulns: list[Vulnerability], *, detail: bool, high_severities: set[str], package_cve_list_threshold: int
):
    if not vulns:
        print(f"  {label}: none")
        return
    print(f"  {label}: {_severity_counts(vulns)}")
    if detail:
        high_vulns = [v for v in vulns if v["Severity"] in high_severities]
        for pkg, vulns_for_pkg in sorted(high_findings_by_package(high_vulns, high_severities).items()):
            print_package_line(pkg, vulns_for_pkg, package_cve_list_threshold)


def _print_candidate_header(i: int, total: int, candidate: DiffCandidate):
    print(
        f"[{i}/{total}] {candidate['repository']}: {candidate['version']} -> "
        f"{candidate['proposed_label']}  [{candidate['kind']}]"
    )


def print_candidate_result(
    closed: list[Vulnerability],
    introduced: list[Vulnerability],
    *,
    detail: bool,
    high_severities: set[str],
    package_cve_list_threshold: int,
):
    """Print one candidate's "closed"/"introduced" CVE-diff lines (see
    _print_direction) followed by a blank separator line."""
    _print_direction(
        "closed",
        closed,
        detail=detail,
        high_severities=high_severities,
        package_cve_list_threshold=package_cve_list_threshold,
    )
    _print_direction(
        "introduced",
        introduced,
        detail=detail,
        high_severities=high_severities,
        package_cve_list_threshold=package_cve_list_threshold,
    )
    print()


def classify_candidates(
    chart_dir: Path, extra_args: list[str], candidates: list[DiffCandidate], values_lines: list[str]
) -> list[ClassifiedCandidate]:
    """Each candidate with its "bucket" ("own"|"partner"|"other"), via the
    exact same own/partner/other classification lib.
    checks.cve/lib.image.upgrade_check already use for a currently-pinned
    image: render-based "# Source:" attribution first (rendered_labels),
    falling back to a values.yaml top-level-key heuristic
    (classify_by_key) for a component not present in the render at all
    (e.g. disabled in the CI values). A render failure here degrades to
    classify_by_key for every candidate, never a crash or a failed step
    — this check never fails. render_chart is memoized (lib.render_scope's
    own _render_cache), and "Image upgrades" already runs before this step
    (STEP_PREREQUISITES) with the same extra_args, so this call is a free
    cache hit in the normal pipeline, not a second real `helm template`."""
    result = render_chart(chart_dir, extra_args)
    vendor_map = friendly_vendor_charts(chart_dir)
    dep_names = dependency_names(chart_dir)
    rendered_labels = render_image_labels(result.stdout, vendor_map) if result.returncode == 0 else {}

    classified: list[ClassifiedCandidate] = []
    for candidate in candidates:
        label = rendered_labels.get((candidate["repository"], candidate["version"], candidate["current_digest"]))
        if label is None:
            top_key = top_level_key_for_line(values_lines, candidate["line"]) if candidate["line"] else None
            label = classify_by_key(top_key, dep_names, vendor_map)
        classified.append({**candidate, "bucket": bucket_of(label)})
    return classified


def _process_bucket(context: DiffContext, title: str, bucket_candidates: list[ClassifiedCandidate]):
    """Scan and print one bucket's candidates under its own "--- <title>
    ---" header (skipped entirely when the bucket is empty, via the same
    lib.checks.cve.print_bucket_header idiom print_bucket_report itself
    uses — not a second independently-written copy of that check). Returns
    (closed, introduced) totals for this bucket. Local per-bucket
    numbering ([i/N] where N is THIS bucket's own count), same convention
    every other bucketed check in this codebase uses."""
    if not print_bucket_header(title, empty=not bucket_candidates):
        return 0, 0

    total_closed = total_introduced = 0
    for i, candidate in enumerate(bucket_candidates, 1):
        _print_candidate_header(i, len(bucket_candidates), candidate)
        current_vulns = _scan_current(context, candidate)
        if current_vulns is None:
            context.scan_errors.append(candidate["current_ref"])
            print(f"  [SCAN-ERR] {candidate['current_ref']}  trivy scan failed or produced unparseable output")
            continue
        proposed_vulns = _scan_proposed(context, candidate)
        if proposed_vulns is None:
            context.scan_errors.append(candidate["proposed_ref"])
            print(f"  [SCAN-ERR] {candidate['proposed_ref']}  trivy scan failed or produced unparseable output")
            continue
        closed, introduced = diff_vulns(current_vulns, proposed_vulns)
        total_closed += len(closed)
        total_introduced += len(introduced)
        print_candidate_result(
            closed,
            introduced,
            detail=context.detail,
            high_severities=context.high_severities,
            package_cve_list_threshold=context.package_cve_list_threshold,
        )
    return total_closed, total_introduced


def _partition_by_bucket(candidates: list[ClassifiedCandidate]) -> list[CandidateBucket]:
    """[(bucket_key, title, candidates-in-that-bucket)] for the three
    report buckets, own/partner/other, in print order — see
    _process_all_buckets/_build_detail_message, which both iterate this
    same list rather than re-deriving own/partner/other separately."""
    titles = (("own", "Own images"), ("partner", "Partner-vendor images"), ("other", "Other-vendor images"))
    return [(key, title, [c for c in candidates if c["bucket"] == key]) for key, title in titles]


def _build_diff_context(chart_dir: Path, *, detail: bool):
    """The DiffContext every _process_bucket/_scan_current/_scan_proposed
    call in one check_cve_diff run shares — split out purely to keep
    check_cve_diff's own local count down."""
    old_cache, new_cache = open_cache_session(chart_dir)
    return DiffContext(
        chart_dir=chart_dir,
        cache=CacheSession(old_cache, new_cache),
        scan_errors=[],
        detail=detail,
        ttl_days=cve_scan_cache_ttl_days(chart_dir),
        high_severities=cve_high_severity_levels(chart_dir),
        package_cve_list_threshold=cve_max_cves_per_package_before_summarizing(chart_dir),
    )


def _process_all_buckets(context: DiffContext, buckets: list[CandidateBucket]) -> dict[str, tuple[int, int]]:
    """{bucket_key: (closed, introduced)} — runs _process_bucket for each
    (bucket_key, title, candidates) triple from _partition_by_bucket."""
    return {key: _process_bucket(context, title, bucket_candidates) for key, title, bucket_candidates in buckets}


def _build_detail_message(buckets: list[CandidateBucket], totals: dict[str, tuple[int, int]], scan_errors: list[str]):
    """check_cve_diff's own detail string: per-bucket candidate/closed/
    introduced counts (own/partner-vendor/other-vendor, in that order)
    plus the scan error count."""
    labels = {"own": "own", "partner": "partner-vendor", "other": "other-vendor"}
    parts: list[str] = []
    for key, _, bucket_candidates in buckets:
        closed, introduced = totals[key]
        parts.append(f"{len(bucket_candidates)} {labels[key]} ({closed} closed, {introduced} introduced)")
    return ", ".join(parts) + f"; {len(scan_errors)} scan error(s)"


def check_cve_diff(chart_dir: Path, extra_args: list[str], *, detail: bool = False):
    """Entry point for the "CVE diff" step (see module docstring for the
    full design): gathers every upgrade-available/sliding-digest
    candidate (gather_candidates), classifies each into the own/partner/
    other buckets (classify_candidates), then scans and prints a
    current-vs-proposed CVE diff per candidate (_process_bucket), sharing
    cve-scan-cache.json with check_cves via lib.checks.cve.scan_cached.
    Always returns True — like check_cves, a diff result here is a triage
    signal for a human, never a chart-correctness failure. The detail
    string carries per-bucket candidate/closed/introduced counts plus any
    scan error count."""
    candidates = gather_candidates(chart_dir)

    if not candidates:
        print("OK: no upgrade-available or sliding-digest candidate to diff")
        return True, "0 candidate(s)"

    values_lines = (chart_dir / "values.yaml").read_text(encoding="utf-8").splitlines()
    buckets = _partition_by_bucket(classify_candidates(chart_dir, extra_args, candidates, values_lines))

    print(f"Diffing CVEs for {len(candidates)} upgrade/slide candidate(s) (current vs proposed, via trivy)...")

    context = _build_diff_context(chart_dir, detail=detail)
    totals = _process_all_buckets(context, buckets)
    save_cache(chart_dir, context.cache.new_cache)

    if context.scan_errors:
        print(f"{len(context.scan_errors)} image(s) could not be scanned:")
        for ref in context.scan_errors:
            print(f"  {ref}")

    return True, _build_detail_message(buckets, totals, context.scan_errors)
