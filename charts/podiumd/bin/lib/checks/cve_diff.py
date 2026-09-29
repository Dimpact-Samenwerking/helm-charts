"""Report-only CVE diff between the pinned image and its proposed replacement.

Candidates: images with a newer tag in the image-upgrade cache ("upgrade") and pins
whose tag's digest moved upstream ("sliding digest"). Both sides are scanned with trivy
and the exact CVE set difference (closed/introduced) is reported. Never fails: a new
CRITICAL is a triage signal, not a chart-correctness fact.

A separate step so the cheap upgrade/digest checks don't carry docker+trivy cost;
only flagged candidates get scanned. verify-podiumd runs "Image upgrades" first as a
prerequisite to populate the upgrade cache.

Buckets own/partner-vendor/other-vendor like check_cves, identical output for all three.

For sliding pins both refs are digest-pinned: the tag alone now resolves to the new
digest, not what is pinned. A pin both sliding and upgradable is reported twice.

Both sides share cve-scan-cache.json with check_cves. The current side is usually a
cache hit; an upgrade's proposed tag costs one manifest lookup to get a cacheable digest,
falling back to an uncached scan if that lookup fails.
"""

import tarfile
import urllib.error

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from typing import TypedDict

import yaml

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
    """(closed, introduced): findings present on only one side, by (VulnerabilityID, PkgName).

    A set difference, not a count subtraction, so "5 closed, 3 introduced" isn't shown as "net -2".
    """
    current_by_key = {_vuln_key(v): v for v in current_vulns}
    proposed_by_key = {_vuln_key(v): v for v in proposed_vulns}
    closed = [v for key, v in current_by_key.items() if key not in proposed_by_key]
    introduced = [v for key, v in proposed_by_key.items() if key not in current_by_key]
    return closed, introduced


def _bare_digest(digest_ref: str):
    """ "sha256:<hex>" -> "<hex>", the form lib.checks.cve.cache_key expects."""
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
    """Every upgrade and sliding-digest candidate (see module docstring).

    proposed_digest is known for a sliding digest; for an upgrade (a bare tag) it is None
    and resolved lazily by _scan_proposed.
    """
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
    """check_cve_diff's per-run inputs, shared by every bucket (see _build_diff_context)."""

    chart_dir: Path
    cache: CacheSession
    scan_errors: list[str]
    detail: bool
    ttl_days: int
    high_severities: set[str]
    package_cve_list_threshold: int


def _scan_current(context: DiffContext, candidate: DiffCandidate):
    """Scan the pinned side; usually a cache hit from check_cves."""
    vulns, _ = scan_cached(
        context.chart_dir,
        ScanTarget(candidate["repository"], candidate["current_digest"], candidate["current_ref"]),
        context.cache,
        context.ttl_days,
        label="current",
    )
    return vulns


def _scan_proposed(context: DiffContext, candidate: DiffCandidate):
    """Scan the proposed side, resolving an upgrade tag's digest first so it can be cached.

    A failed resolve falls back to an uncached scan rather than failing the candidate.
    """
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
    """Print one candidate's closed/introduced lines and a blank line."""
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
    """Each candidate with its bucket, classified like lib.checks.cve.

    A render failure (or file/process/.tgz/YAML/Chart.yaml error) degrades to
    classify_by_key rather than failing: this check never fails. render_chart is memoized
    and "Image upgrades" already rendered with the same args, so this is normally free.
    """
    try:
        result = render_chart(chart_dir, extra_args)
        vendor_map = friendly_vendor_charts(chart_dir)
        dep_names = dependency_names(chart_dir)
        rendered_labels = render_image_labels(result.stdout, vendor_map) if result.returncode == 0 else {}
    except (OSError, tarfile.TarError, yaml.YAMLError, KeyError, TypeError, ValueError):
        vendor_map = {}
        dep_names: set[str] = set()
        rendered_labels = {}

    classified: list[ClassifiedCandidate] = []
    for candidate in candidates:
        label = rendered_labels.get((candidate["repository"], candidate["version"], candidate["current_digest"]))
        if label is None:
            top_key = top_level_key_for_line(values_lines, candidate["line"]) if candidate["line"] else None
            label = classify_by_key(top_key, dep_names, vendor_map)
        classified.append({**candidate, "bucket": bucket_of(label)})
    return classified


def _process_bucket(context: DiffContext, title: str, bucket_candidates: list[ClassifiedCandidate]):
    """Scan and print one bucket under its header (skipped when empty); return (closed, introduced)."""
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
    """(bucket_key, title, candidates) for own/partner/other, in print order."""
    titles = (("own", "Own images"), ("partner", "Partner-vendor images"), ("other", "Other-vendor images"))
    return [(key, title, [c for c in candidates if c["bucket"] == key]) for key, title in titles]


def _build_diff_context(chart_dir: Path, *, detail: bool):
    """The DiffContext shared by one check_cve_diff run."""
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
    """{bucket_key: (closed, introduced)} for every bucket."""
    return {key: _process_bucket(context, title, bucket_candidates) for key, title, bucket_candidates in buckets}


def _build_detail_message(buckets: list[CandidateBucket], totals: dict[str, tuple[int, int]], scan_errors: list[str]):
    """Per-bucket candidate/closed/introduced counts plus the scan error count."""
    labels = {"own": "own", "partner": "partner-vendor", "other": "other-vendor"}
    parts: list[str] = []
    for key, _, bucket_candidates in buckets:
        closed, introduced = totals[key]
        parts.append(f"{len(bucket_candidates)} {labels[key]} ({closed} closed, {introduced} introduced)")
    return ", ".join(parts) + f"; {len(scan_errors)} scan error(s)"


def check_cve_diff(chart_dir: Path, extra_args: list[str], *, detail: bool = False):
    """The "CVE diff" step. Always returns ok=True; the detail carries per-bucket counts."""
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
