"""Report-only trivy CVE scan (fixable vulnerabilities) of every digest-pinned image in values.yaml.

Never fails: whether a HIGH/CRITICAL fix is reachable or exploitable here is a human
triage decision, not a chart-correctness fact.

Images are bucketed own/partner-vendor/other-vendor by the render's "# Source:"
(falling back to the values.yaml top-level key for components absent from the render),
but every bucket gets the same output. Default: per-image severity totals. --detail:
every finding grouped per package (one bundled binary can carry hundreds of CVEs),
summarized past cve_scan.max_cves_per_package_before_summarizing. FixedVersion is
never shown: only the image tag is pinned here, not packages inside it.

An "upgradable to X" marker comes from the image-upgrade cache, read-only; verify-podiumd
runs "Image upgrades" first as a prerequisite so it is fresh.

Results are cached per (repository, digest) in <repo-root>/.cache/cve-scan-cache.json,
capped by cve_scan.scan_cache_ttl_days because trivy's DB changes even when the image doesn't.
"""

import json
import re
import shutil

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from pathlib import Path
from typing import TypedDict
from typing import TypeGuard

from lib.chart.chart_yaml import load_chart_dependencies
from lib.chart.values_tree_primitives import values_key_of
from lib.image.digests import unique_digest_pin_targets
from lib.image.upgrade_cache import UpgradeEntry
from lib.image.upgrade_cache import cache_entry_is_fresh as upgrade_entry_is_fresh
from lib.image.upgrade_cache import cache_key as upgrade_cache_key
from lib.image.upgrade_cache import load_cache as load_upgrade_cache
from lib.json_cache import cache_file
from lib.json_cache import load_json_cache
from lib.json_cache import save_json_cache
from lib.procutil import run
from lib.registry import parse_repo
from lib.render_scope import OWN_TEMPLATES_PREFIX
from lib.render_scope import chart_name_from_source
from lib.render_scope import friendly_vendor_charts
from lib.render_scope import render_chart
from lib.render_scope import split_rendered_by_source
from lib.settings import cve_max_cves_per_package_before_summarizing
from lib.settings import cve_scan_cache_ttl_days
from lib.settings import image_upgrade_tag_check_cache_ttl_days
from lib.yaml_types import YamlValue
from lib.yaml_types import is_yaml_mapping

TRIVY_IMAGE = "aquasec/trivy:latest"
# Worst first.
SEVERITY_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN"]

# The only fields reported; the rest of trivy's output would just bloat the cache.
# FixedVersion is excluded: only image tags are pinned here, not packages inside them.
VULN_FIELDS = ("VulnerabilityID", "PkgName", "Severity")

CACHE_FILENAME = "cve-scan-cache.json"


class Vulnerability(TypedDict):
    """The VULN_FIELDS of one trivy finding ("?" when trivy left one out)."""

    VulnerabilityID: str
    PkgName: str
    Severity: str


class CveEntry(TypedDict):
    """One cve-scan-cache.json entry: scan time and findings."""

    scanned_at: str
    vulnerabilities: list[Vulnerability]


def _vulnerability(finding: YamlValue) -> Vulnerability | None:
    """The VULN_FIELDS of a trivy finding, or None if it isn't a mapping
    or one of them isn't text."""
    if not isinstance(finding, dict):
        return None
    vuln_id, pkg, severity = (finding.get(name, "?") for name in VULN_FIELDS)
    if not isinstance(vuln_id, str) or not isinstance(pkg, str) or not isinstance(severity, str):
        return None
    return {"VulnerabilityID": vuln_id, "PkgName": pkg, "Severity": severity}


def trivy_vulnerabilities(data: object) -> list[Vulnerability] | None:
    """Every finding in trivy's JSON report `data`, or None when `data`
    does not have trivy's Results/Vulnerabilities shape."""
    if not is_yaml_mapping(data):
        return None
    results = data.get("Results") or []
    if not isinstance(results, list):
        return None
    vulns: list[Vulnerability] = []
    for res in results:
        if not isinstance(res, dict):
            return None
        findings = res.get("Vulnerabilities") or []
        if not isinstance(findings, list):
            return None
        for finding in findings:
            vuln = _vulnerability(finding)
            if vuln is None:
                return None
            vulns.append(vuln)
    return vulns


def is_cve_entry(value: object) -> TypeGuard[CveEntry]:
    """Whether a parsed cache entry is a CveEntry."""
    if not is_yaml_mapping(value) or not isinstance(value.get("scanned_at"), str):
        return False
    vulns = value.get("vulnerabilities")
    return isinstance(vulns, list) and all(isinstance(v, dict) and _vulnerability(v) == v for v in vulns)


class ImageCves(TypedDict):
    """One scanned image in the CVE report: its bucket ("own", "partner",
    "other"), vendor label (partner only), findings and the newer tag the
    upgrade cache knows (None: none known)."""

    bucket: str
    vendor_label: str | None
    vulns: list[Vulnerability]
    upgradable_to: str | None


@dataclass
class ScanTarget:
    """An image for scan_cached; only repository+digest form the cache key."""

    repository: str
    digest: str | None
    ref: str


@dataclass
class CacheSession:
    """scan_cached reads from old_cache and writes into new_cache."""

    old_cache: dict[str, CveEntry]
    new_cache: dict[str, CveEntry]


def cache_path(chart_dir: Path):
    """<repo-root>/.cache/cve-scan-cache.json (gitignored); chart_dir outside a git checkout."""
    return cache_file(chart_dir, CACHE_FILENAME)


def load_cache(chart_dir: Path) -> dict[str, CveEntry]:
    """The parsed cache, or {} if missing or corrupt (never raises)."""
    return load_json_cache(cache_path(chart_dir), is_cve_entry)


def save_cache(chart_dir: Path, cache: dict[str, CveEntry]):
    """Write `cache` to cache_path(chart_dir)."""
    save_json_cache(cache_path(chart_dir), cache)


def open_cache_session(chart_dir: Path):
    """(old_cache, new_cache): a read-only snapshot and the mutable copy scan_cached writes.

    new_cache must start as a copy, not {}, or saving it drops every entry this run
    didn't touch (including cve_diff's "proposed"-side entries). Shared by check_cves
    and check_cve_diff so the two can't diverge.
    """
    old_cache = load_cache(chart_dir)
    return old_cache, dict(old_cache)


def cache_key(repository: str, digest: str):
    """ "repo@sha256:digest": keyed on content, not on which tag points at it."""
    return f"{repository}@sha256:{digest}"


def cache_entry_is_fresh(entry: CveEntry, ttl_days: int):
    """True when `entry` was scanned within the last `ttl_days` days."""
    try:
        scanned_at = datetime.fromisoformat(entry["scanned_at"])
    except (KeyError, ValueError, TypeError):
        return False
    return datetime.now(timezone.utc) - scanned_at < timedelta(days=ttl_days)


def run_trivy(image_ref: str) -> list[Vulnerability] | None:
    """Fixable vulnerabilities in image_ref via `docker run` trivy, or None on failure.

    A non-zero exit is a failure even if stdout parses: it can be empty JSON that
    would otherwise read as a clean scan.
    """
    result = run(
        [
            "docker",
            "run",
            "--rm",
            TRIVY_IMAGE,
            "image",
            "--ignore-unfixed",
            "--scanners",
            "vuln",
            "--format",
            "json",
            image_ref,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    try:
        data: object = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    return trivy_vulnerabilities(data)


def scan_cached(chart_dir: Path, target: ScanTarget, session: CacheSession, ttl_days: int, label: str = "this image"):
    """Scan `target.ref` with trivy, using the digest-keyed cache when `target.digest` is known.

    `target.digest` is bare hex; None skips the cache (nothing to key on).
    `label` prefixes the printed cache-hit/fresh-scan line.

    Returns (vulnerabilities, was_cached), or (None, False) when the scan failed.
    Failures are never cached, so they are retried next run.
    """
    key = cache_key(target.repository, target.digest) if target.digest is not None else None
    if key is not None:
        cached = session.old_cache.get(key)
        if cached and cache_entry_is_fresh(cached, ttl_days):
            session.new_cache[key] = cached
            print(f"  {label}: served from cache — {target.ref}")
            return cached["vulnerabilities"], True

    print(f"  {label}: scanning fresh (docker pull + trivy) — {target.ref}...", flush=True)
    vulns = run_trivy(target.ref)
    if vulns is None:
        return None, False

    if key is not None:
        session.new_cache[key] = {"scanned_at": datetime.now(timezone.utc).isoformat(), "vulnerabilities": vulns}
        save_cache(chart_dir, session.new_cache)  # persist incrementally — a scan sweep can be slow
    return vulns, False


# --- own/partner/other classification ---

# Digest-pinned "image:" lines in a render; every image helper renders a plain scalar.
PINNED_IMAGE_RE = re.compile(r'^\s*image:\s*"?([^"\s]+@sha256:[0-9a-f]{64})"?\s*$', re.MULTILINE)

# Top-level values.yaml key; fallback classification for components absent from the render.
TOP_LEVEL_KEY_RE = re.compile(r"^([a-zA-Z0-9_-]+):")

# A digest-pinned image as (repository, version or None, digest).
ImageKey = tuple[str, str | None, str]
# A scan target as ((repository, version), (digest, values.yaml line)).
ScanTargetPin = tuple[tuple[str, str], tuple[str, int]]


def parse_image_ref(ref: str) -> ImageKey:
    """ "<repository>[:<version>]@sha256:<digest>" -> (repository, version, digest).

    version is None for a tagless ref; a "host:port" colon is not a tag (a tag has no "/").
    """
    repo_and_tag, digest = ref.rsplit("@sha256:", 1)
    repository, sep, version = repo_and_tag.rpartition(":")
    if not sep or "/" in version:
        return repo_and_tag, None, digest
    return repository, version, digest


def dependency_names(chart_dir: Path):
    """Every direct Chart.yaml dependency alias (or name when unaliased)."""
    return {values_key_of(dep) for dep in load_chart_dependencies(chart_dir / "Chart.yaml")}


def top_level_key_for_line(lines: list[str], line_no: int):
    """The nearest top-level key above `line_no` (0-based), or None."""
    for i in range(line_no - 1, -1, -1):
        m = TOP_LEVEL_KEY_RE.match(lines[i])
        if m:
            return m.group(1)
    return None


def classify_source(source: str, vendor_map: dict[str, str]) -> str:
    """ "own" | a vendor label | "other", from a rendered "# Source:" path."""
    if source.startswith(OWN_TEMPLATES_PREFIX):
        return "own"
    return vendor_map.get(chart_name_from_source(source), "other")


def classify_by_key(top_level_key: str | None, dep_names: set[str], vendor_map: dict[str, str]) -> str:
    """classify_source's fallback for an image absent from the render.

    "own" when no dependency has this key (only a podiumd template can use it).
    """
    if top_level_key is None or top_level_key not in dep_names:
        return "own"
    return vendor_map.get(top_level_key, "other")


def bucket_of(label: str) -> str:
    """ "own"/"other" unchanged; any vendor label -> "partner"."""
    if label in ("own", "other"):
        return label
    return "partner"


def render_image_labels(rendered_text: str, vendor_map: dict[str, str]) -> dict[ImageKey, str]:
    """(repository, version, digest) -> label for every pinned image in the render.

    "own" wins if any source is own, even when a vendored chart also renders it.
    """
    labels: dict[ImageKey, str] = {}
    for source, text in split_rendered_by_source(rendered_text):
        label = classify_source(source, vendor_map)
        for ref in PINNED_IMAGE_RE.findall(text):
            key = parse_image_ref(ref)
            if labels.get(key) != "own":
                labels[key] = label
    return labels


@dataclass
class ImageClassification:
    """Inputs for classifying a scan target (see _target_label)."""

    rendered_labels: dict[ImageKey, str]
    dep_names: set[str]
    vendor_map: dict[str, str]


@dataclass
class CveScanSettings:
    """check_cves' lib.settings values, resolved once per run."""

    package_cve_list_threshold: int
    cve_cache_ttl_days: int
    upgrade_cache_ttl_days: int


@dataclass
class ScanContext:
    """check_cves' per-run scan inputs."""

    chart_dir: Path
    values_lines: list[str]
    classification: ImageClassification
    upgrade_cache: dict[str, UpgradeEntry]
    session: CacheSession
    settings: CveScanSettings


@dataclass
class ReportSettings:
    """print_bucket_report's per-run settings."""

    detail_level: str
    package_cve_list_threshold: int


@dataclass
class BucketRefs:
    """Refs with findings per report bucket (see _bucket_refs)."""

    own: list[str]
    partner: list[str]
    other: list[str]


@dataclass
class ScanStats:
    """_scan_all_targets' run-level counters."""

    scan_errors: list[str]
    cache_hits: int
    target_count: int


def _classify_pinned_images(chart_dir: Path, extra_args: list[str]):
    """An ImageClassification if the chart renders successfully, else
    None (the caller reports "helm template failed to render" and stops)."""
    result = render_chart(chart_dir, extra_args)
    if result.returncode != 0:
        return None
    vendor_map = friendly_vendor_charts(chart_dir)
    dep_names = dependency_names(chart_dir)
    rendered_labels = render_image_labels(result.stdout, vendor_map)
    return ImageClassification(rendered_labels, dep_names, vendor_map)


def _image_ref(repository: str, version: str):
    """The pullable "<host>/<repo_path>:<version>" ref (not the stripped/mirror form)."""
    host, repo_path = parse_repo(repository)
    return f"{host}/{repo_path}:{version}"


def _digest_ref(repository: str, digest: str | None) -> str | None:
    """ "<host>/<repo_path>@sha256:<digest>" for `repository`, or None
    without a digest."""
    if not digest:
        return None
    host, repo_path = parse_repo(repository)
    return f"{host}/{repo_path}@sha256:{digest}"


def _target_label(repository: str, version: str, digest: str, line: int, context: ScanContext):
    """The render-based label, else classify_by_key's top-level-key fallback."""
    label = context.classification.rendered_labels.get((repository, version, digest))
    if label is not None:
        return label
    top_key = top_level_key_for_line(context.values_lines, line)
    return classify_by_key(top_key, context.classification.dep_names, context.classification.vendor_map)


def _upgradable_to(repository: str, version: str, context: ScanContext) -> str | None:
    """The newer tag from a fresh upgrade-cache entry, or None."""
    upgrade_entry = context.upgrade_cache.get(upgrade_cache_key(repository, version))
    if (
        upgrade_entry
        and upgrade_entry_is_fresh(upgrade_entry, context.settings.upgrade_cache_ttl_days)
        and upgrade_entry["newest"] != version
    ):
        return upgrade_entry["newest"]
    return None


def _scan_one_target(
    repo_version: tuple[str, str], digest_line: tuple[str, int], index: int, total: int, context: ScanContext
):
    """(image_ref, entry, was_cached); entry is None when the scan failed.

    image_ref (tag-based) is for display; trivy scans the pinned digest, since the tag
    may have been republished since pinning.
    """
    repository, version = repo_version
    digest, line = digest_line
    image_ref = _image_ref(repository, version)
    scan_ref = _digest_ref(repository, digest) or image_ref
    label = _target_label(repository, version, digest, line, context)

    vulns, was_cached = scan_cached(
        context.chart_dir,
        ScanTarget(repository, digest, scan_ref),
        context.session,
        context.settings.cve_cache_ttl_days,
        label=f"[{index}/{total}] this image",
    )
    if vulns is None:
        return image_ref, None, False

    entry: ImageCves = {
        "bucket": bucket_of(label),
        "vendor_label": label if bucket_of(label) == "partner" else None,
        "vulns": vulns,
        "upgradable_to": _upgradable_to(repository, version, context),
    }
    return image_ref, entry, was_cached


def _scan_all_targets(targets: list[ScanTargetPin], context: ScanContext):
    """(images, ScanStats) for every target, printing progress as it goes."""
    print(
        f"Scanning {len(targets)} unique pinned image(s) for known CVEs with trivy "
        f"(pulls every image not already cached — this can take a while)..."
    )
    images: dict[str, ImageCves] = {}
    scan_errors: list[str] = []
    cache_hits = 0
    for i, (repo_version, digest_line) in enumerate(targets, 1):
        image_ref, entry, was_cached = _scan_one_target(repo_version, digest_line, i, len(targets), context)
        if entry is None:
            scan_errors.append(image_ref)
            print(f"  [SCAN-ERR] {image_ref}  trivy scan failed or produced unparseable output")
            continue
        if was_cached:
            cache_hits += 1
        images[image_ref] = entry
    return images, ScanStats(scan_errors, cache_hits, len(targets))


def _bucket_refs(images: dict[str, ImageCves]):
    """(own_refs, partner_refs, other_refs) with at least one finding, in insertion order."""

    def refs_in(bucket: str):
        return [ref for ref, info in images.items() if info["bucket"] == bucket and info["vulns"]]

    return refs_in("own"), refs_in("partner"), refs_in("other")


def _print_bucket_reports(images: dict[str, ImageCves], buckets: BucketRefs, report_settings: ReportSettings):
    print_bucket_report("Own images", buckets.own, images, report_settings)
    print_bucket_report("Partner-vendor images", buckets.partner, images, report_settings)
    print_bucket_report("Other-vendor images", buckets.other, images, report_settings)


def _print_cve_summary_lines(buckets: BucketRefs, stats: ScanStats, cve_cache_ttl_days: int):
    if not (buckets.own or buckets.partner or buckets.other):
        print("OK: no known CVEs found across pinned images")
    if stats.scan_errors:
        print(f"{len(stats.scan_errors)} image(s) could not be scanned:")
        for ref in stats.scan_errors:
            print(f"  {ref}")
    print(
        f"{stats.cache_hits}/{stats.target_count} image(s) served from cache (unchanged digest, "
        f"scanned within the last {cve_cache_ttl_days} days)"
    )


def _cve_summary_detail(buckets: BucketRefs, images: dict[str, ImageCves], stats: ScanStats):
    """check_cves' summary detail string."""
    own_n, own_cve = bucket_totals(buckets.own, images)
    partner_n, partner_cve = bucket_totals(buckets.partner, images)
    other_n, other_cve = bucket_totals(buckets.other, images)
    return (
        f"CVEs: {own_cve} own ({own_n} img), {partner_cve} partner-vendor ({partner_n} img), "
        f"{other_cve} other-vendor ({other_n} img); {len(stats.scan_errors)} scan error(s)"
    )


def check_cves(chart_dir: Path, extra_args: list[str], *, detail: bool = False):
    """The "CVE scan" step: scan and report every pinned image per bucket.

    Returns (ok, detail); ok is False only when the chart fails to render.
    """
    if shutil.which("docker") is None:
        return True, "docker is not installed — skipped (see --help)"

    settings = CveScanSettings(
        cve_max_cves_per_package_before_summarizing(chart_dir),
        cve_scan_cache_ttl_days(chart_dir),
        image_upgrade_tag_check_cache_ttl_days(chart_dir),
    )

    classification = _classify_pinned_images(chart_dir, extra_args)
    if classification is None:
        return False, "helm template failed to render"

    values_lines = (chart_dir / "values.yaml").read_text(encoding="utf-8").splitlines()
    targets = sorted(unique_digest_pin_targets(values_lines).items())
    session = CacheSession(*open_cache_session(chart_dir))
    scan_context = ScanContext(
        chart_dir, values_lines, classification, load_upgrade_cache(chart_dir), session, settings
    )

    images, stats = _scan_all_targets(targets, scan_context)

    # Untouched entries (e.g. cve_diff "proposed" images) are kept; they age out via the TTL.
    save_cache(chart_dir, session.new_cache)

    buckets = BucketRefs(*_bucket_refs(images))
    report_settings = ReportSettings("full" if detail else "totals", settings.package_cve_list_threshold)
    _print_bucket_reports(images, buckets, report_settings)
    _print_cve_summary_lines(buckets, stats, settings.cve_cache_ttl_days)

    return True, _cve_summary_detail(buckets, images, stats)


def bucket_totals(refs: list[str], images: dict[str, ImageCves]):
    """(image count, total vulnerability count) for `refs`."""
    return len(refs), sum(len(images[ref]["vulns"]) for ref in refs)


def severity_label(severity: str):
    """ "CRITICAL" -> "CRIT"; other severities unchanged."""
    return "CRIT" if severity == "CRITICAL" else severity


def findings_by_package(vulns: list[Vulnerability]) -> dict[str, list[Vulnerability]]:
    """PkgName -> its findings, every severity (one package can carry many CVE IDs)."""
    groups: dict[str, list[Vulnerability]] = {}
    for v in vulns:
        groups.setdefault(v["PkgName"], []).append(v)
    return groups


def print_findings_per_package(vulns: list[Vulnerability], threshold: int) -> None:
    """One print_package_line per affected package, in package order."""
    for pkg, vulns_for_pkg in sorted(findings_by_package(vulns).items()):
        print_package_line(pkg, vulns_for_pkg, threshold)


def print_package_line(pkg: str, vulns_for_pkg: list[Vulnerability], threshold: int):
    """Print `pkg`'s CVE IDs worst-first, or per-severity counts when more than `threshold`."""
    ordered = sorted(vulns_for_pkg, key=lambda v: SEVERITY_ORDER.index(v["Severity"]))

    if len(ordered) <= threshold:
        ids = ", ".join(f"{severity_label(v['Severity'])} {v['VulnerabilityID']}" for v in ordered)
        print(f"  {pkg}: {ids}")
        return

    counts = Counter(v["Severity"] for v in ordered)
    parts = ", ".join(f"{counts[s]} {severity_label(s)}" for s in SEVERITY_ORDER if counts.get(s))
    print(f"  {pkg}: {len(ordered)} CVE(s) ({parts})")


def print_severity_totals_line(vulns: list[Vulnerability]):
    """Print per-severity counts for `vulns`, worst first."""
    counts = Counter(v["Severity"] for v in vulns)
    parts = ", ".join(f"{counts[s]} {severity_label(s)}" for s in SEVERITY_ORDER if counts.get(s))
    print(f"  {parts} CVE(s)")


def print_bucket_header(title: str, *, empty: bool):
    """Print "--- {title} ---" unless `empty`; return whether it was printed."""
    if empty:
        return False
    print(f"--- {title} ---")
    return True


def print_bucket_report(title: str, refs: list[str], images: dict[str, ImageCves], settings: ReportSettings):
    """Print one bucket's images per settings.detail_level (same for every bucket).

    "full": per-image severity totals, then every finding itemized per package.
    "totals": per-image severity totals only.
    """
    if not print_bucket_header(title, empty=not refs):
        return

    for ref in refs:
        info = images[ref]
        vendor = f" [{info['vendor_label']}]" if info["vendor_label"] else ""
        upgradable = f" upgradable to {info['upgradable_to']}" if info["upgradable_to"] else ""
        print(f"{ref}{vendor}{upgradable}")

        print_severity_totals_line(info["vulns"])
        if settings.detail_level == "full":
            print_findings_per_package(info["vulns"], settings.package_cve_list_threshold)

        print()
