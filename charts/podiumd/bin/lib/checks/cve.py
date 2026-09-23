"""Report-only sweep for known CVEs (with a fix available) against every
digest-pinned image in values.yaml, via a per-image `docker run
aquasec/trivy:latest image` scan — the same tool and invocation shape this
repo already uses to scan images in
.github/workflows/trivy-vuln-scanner.yaml. Companion to check_image_digests
(which only catches the SAME tag's digest moving) and to Renovate (which
lags on niche images per .claude/commands/check-image-cves.md) — this
catches "a newer tag exists with a known fix" regardless of whether the
currently-pinned tag has drifted.

Slowest step in the pipeline by far — scanning every unique pinned image
pulls each one via Docker — but runs by default like every other step
(see --skip=cve-scan/--include=cve-scan in verify-podiumd). Never
fails the check regardless of severity found — a HIGH/CRITICAL CVE with a
fix available is a triage decision for a human (is the fix actually
reachable here, is the severity exploitable in this deployment, ...), not
a chart-correctness fact this script can gate on.

Same own/partner-vendor/other-vendor scope split as check_yamllint/
check_kubeconform/check_shellcheck/check_kube_score, but — unlike those —
every bucket gets IDENTICAL output here, own/partner/other alike (see
print_bucket_report's detail_level): no special-cased aggregate-only
rollup for other-vendor, so an other-vendor image with a finding is just
as visible as an own or partner one. By default every bucket gets
per-image severity totals only (every severity, including CRITICAL/HIGH)
— no package breakdown, no individual CVE IDs. Pass --detail to switch
every bucket to full itemization instead: CRITICAL/HIGH findings per
image, grouped by the affected package/file rather than listed flat — a
bundled binary like gotenberg's Chromium can carry hundreds of
individually-tracked CVEs against the *same* package, so each package
gets one line listing its CVE IDs, or — past cve_scan.max_cves_per_package_
before_summarizing (lib.settings) — a single summarized count instead of
hundreds of IDs nobody will triage
individually. MEDIUM/LOW/UNKNOWN are still only totaled per image, even
with --detail — nothing in this repo can act on those package-by-package
either, so itemizing them would just be noise.

Each image's line also carries an inline "upgradable to X" marker when
lib.image.upgrade_check's own cache (charts/podiumd/image-upgrade-
cache.json, via lib.image.upgrade_cache) has a fresh entry showing a
newer same-variant tag is published — read-only here, purely best-effort:
if there's no fresh cache entry (that check hasn't run recently, or this
image wasn't in its scope), the marker is just omitted rather than
triggering a registry call of this module's own. Whether the newer tag
actually fixes anything is a separate question this module can't answer.
"CVE scan" lists "Image upgrades" as a STEP_PREREQUISITES entry in
verify-podiumd specifically so this cache is always freshly populated
first — a bare --include=cve-scan still gets it, not just a full run.
Ownership is
determined primarily from the `helm template` render (same authoritative
"# Source:" attribution the other checks use — this also correctly
classifies a podiumd-owned template that happens to reuse a vendored
dependency's values namespace, e.g. kiss.adapter or redis-ha's own
label-master CronJob, as "own"), falling back to a values.yaml top-level-
key heuristic only for a component not present in the render at all (e.g.
disabled in the CI values) — matches a Chart.yaml dependency name/alias
means vendored, anything else means a podiumd-owned template configures
it.

Whether a newer tag is published at all (regardless of whether it fixes
anything) is a separate, standalone check — see lib.image.upgrade_check —
split out from here since the two questions are independent: a newer tag
existing doesn't mean it fixes a given CVE, and that check's answer is
useful even for an image with zero findings here.

Scan results are cached by (repository, digest) in
<repo-root>/.cache/cve-scan-cache.json — a personal, gitignored,
per-checkout cache (see cache_path), not shared between contributors or
CI: each of those re-scans an image the first time they see its digest,
same as a cold cache after cloning fresh. Keyed on digest, not version,
so a sliding tag republished under the same version string still
invalidates correctly. Capped by cve_scan.scan_cache_ttl_days (lib.
settings) even for an unchanged digest — the image content never
changes, but trivy's own vulnerability
DB does, so a digest that scanned clean a month ago may have a
newly-disclosed CVE against it today. Each cached vulnerability is
trimmed to just the three fields the report actually uses
(VulnerabilityID/PkgName/Severity) — trivy's raw Title/Description/
References/CVSS/dates/FixedVersion would otherwise bloat the cache file
for no reporting benefit. FixedVersion in particular is never shown: this
repo only ever pins a base image tag/digest, never an individual
OS/language package version inside that image, so "upgrade to version X"
for one bundled package isn't an actionable step here — whether a newer
image tag exists at all is lib.image.upgrade_check's job, not this
module's."""

import json
import re
import shutil

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
from datetime import timezone

from lib.chart.release_baseline_basics import load_yaml
from lib.chart.values_tree_primitives import values_key_of
from lib.gitutil import find_repo_root
from lib.image.digests import unique_digest_pin_targets
from lib.image.upgrade_cache import cache_entry_is_fresh as upgrade_entry_is_fresh
from lib.image.upgrade_cache import cache_key as upgrade_cache_key
from lib.image.upgrade_cache import load_cache as load_upgrade_cache
from lib.procutil import run
from lib.registry import parse_repo
from lib.render_scope import OWN_TEMPLATES_PREFIX
from lib.render_scope import chart_name_from_source
from lib.render_scope import friendly_vendor_charts
from lib.render_scope import render_chart
from lib.render_scope import split_rendered_by_source
from lib.settings import cve_high_severity_levels
from lib.settings import cve_max_cves_per_package_before_summarizing
from lib.settings import cve_scan_cache_ttl_days
from lib.settings import image_upgrade_tag_check_cache_ttl_days

TRIVY_IMAGE = "aquasec/trivy:latest"
# Trivy's own severities, worst first — anything else (a future severity
# trivy adds) sorts last rather than crashing.
SEVERITY_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN"]

# Only these three fields are ever used for reporting — everything else
# trivy returns per vulnerability (Title, Description, References, CVSS
# scores, published/last-modified dates, FixedVersion, ...) is dead weight
# in the cache. FixedVersion is deliberately excluded even though trivy
# reports it: this repo only pins a base image tag/digest, never an
# individual package version inside that image, so it's not information
# this report can act on (see describe_newest_tag for the check that is).
VULN_FIELDS = ("VulnerabilityID", "PkgName", "Severity")

CACHE_FILENAME = "cve-scan-cache.json"


@dataclass
class ScanTarget:
    """repository/digest/ref — the image scan_cached is being asked to
    scan, bundled since every call site already has all three together.
    cache_key only ever needs repository+digest, never the full ref."""

    repository: str
    digest: str
    ref: str


@dataclass
class CacheSession:
    """old_cache/new_cache — open_cache_session's own return pair,
    bundled since scan_cached needs both together on every call (read
    from old_cache, write into new_cache)."""

    old_cache: dict
    new_cache: dict


def cache_path(chart_dir):
    """<repo-root>/.cache/cve-scan-cache.json — a personal, gitignored,
    per-checkout cache (see module docstring), never committed. Rooted at
    the repo root (not chart_dir) so root .gitignore's plain /.cache/
    entry covers it without a chart-specific rule. Falls back to chart_dir
    itself if it isn't inside a git checkout."""
    root = find_repo_root(chart_dir) or chart_dir
    return root / ".cache" / CACHE_FILENAME


def load_cache(chart_dir):
    """The parsed contents of cache_path(chart_dir), or {} if the file
    doesn't exist yet or can't be parsed (corrupt/truncated) — never
    raises, so a broken cache just behaves like a cold one."""
    path = cache_path(chart_dir)
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_cache(chart_dir, cache):
    """Persist `cache` to cache_path(chart_dir) as pretty-printed,
    key-sorted JSON, creating the .cache directory first if needed."""
    path = cache_path(chart_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, indent=2, sort_keys=True), encoding="utf-8")


def open_cache_session(chart_dir):
    """(old_cache, new_cache) — old_cache is this run's read-only snapshot
    (what a cache-hit check compares against); new_cache is a SEPARATE,
    mutable copy scan_cached actually writes into and saves as the run
    progresses. Both check_cves and lib.checks.cve_diff.check_cve_diff
    need exactly this same two-line "load, then start a correct working
    copy" step — factored out here, the one place both now call, so
    there's no second independently-written copy of it left to silently
    diverge again (real bug, already happened once: check_cves used to
    write new_cache = {} instead of dict(old_cache), which wiped out
    every entry it didn't itself touch — including every cve_diff_check
    "proposed"-side entry — the moment its own save_cache ran)."""
    old_cache = load_cache(chart_dir)
    return old_cache, dict(old_cache)


def cache_key(repository, digest):
    """The cve-scan-cache.json key for one (repository, digest) pin — the
    same "repo@sha256:digest" shape used as an image ref minus the tag,
    so a cache hit is keyed purely on content, never on which tag
    currently happens to point at that digest."""
    return f"{repository}@sha256:{digest}"


def cache_entry_is_fresh(entry, ttl_days):
    """True when `entry` was scanned within the last `ttl_days` days (see
    cve_scan.scan_cache_ttl_days in lib.settings — long enough that a
    routine run doesn't re-pull/re-scan every image every time; short
    enough that a stale "no findings" cache entry doesn't silently hide
    a CVE disclosed against that digest after it was last scanned)."""
    try:
        scanned_at = datetime.fromisoformat(entry["scanned_at"])
    except (KeyError, ValueError, TypeError):
        return False
    return datetime.now(timezone.utc) - scanned_at < timedelta(days=ttl_days)


def run_trivy(image_ref):
    """Scan image_ref with trivy (via `docker run`, same shape as this
    repo's own trivy-vuln-scanner.yaml workflow — --ignore-unfixed so only
    vulnerabilities with an actual fix available are returned, matching
    what's relevant to "should we bump this image"). Returns the flat list
    of trimmed vulnerability dicts (see VULN_FIELDS), or None if trivy's
    own output couldn't be parsed as JSON (a pull failure or trivy crash,
    not a chart problem)."""
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
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None

    vulns = []
    for res in data.get("Results") or []:
        vulns.extend({field: v.get(field, "?") for field in VULN_FIELDS} for v in res.get("Vulnerabilities") or [])
    return vulns


def scan_cached(chart_dir, target, session, ttl_days, label="this image"):
    """Scan `target.ref` via trivy, reusing THIS module's own digest-keyed
    cve-scan-cache.json whenever `target.digest` (bare hex, no "sha256:"
    prefix) is known — the one shared "look up this (repository, digest)
    in the cache; if fresh, report a cache hit and return the cached
    vulnerabilities; otherwise announce a fresh scan, run_trivy, cache
    the result, and return it" primitive both check_cves' own per-image
    loop (below) and lib.checks.cve_diff's own current/proposed scans
    route through — the two used to each hand-roll this same logic
    separately. `target.digest=None` skips the cache tier entirely,
    straight to run_trivy — used by cve_diff_check for a proposed tag
    whose digest couldn't be resolved; never persisted either, since
    there's no digest to key it by. `ttl_days` (see cve_scan.scan_cache_
    ttl_days in lib.settings) is resolved once by the caller and passed
    straight through to cache_entry_is_fresh, rather than re-read here on
    every call. `session` is a CacheSession (old_cache/new_cache, see
    open_cache_session).

    `label` prefixes the printed cache-hit/fresh-scan line, so each
    caller can tell its own calls apart in the output: cve_diff_check
    passes "current"/"proposed" (two scans per candidate, needing a side
    label); check_cves passes its own "[i/N] this image" (one scan per
    image, no side to distinguish, but still wants its own progress
    index) — the default "this image" is just a sane fallback for a
    caller that doesn't need either.

    Returns (vulnerabilities, was_cached) on success — was_cached tells a
    caller like check_cves whether to count this toward its own aggregate
    cache-hit total, without re-deriving that from scratch. Returns
    (None, False) if trivy's own scan failed or produced unparseable
    output; a failure is never cached (either tier), so a caller can
    freely retry it on the next run rather than a failure being wrongly
    remembered as a real (empty) result."""
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

# Every "image:" line in a `helm template` render whose value is digest-
# pinned — the rendered form of podiumd.image (and any vendored chart's
# own equivalent) always ends up as a plain scalar, regardless of which
# helper produced it.
PINNED_IMAGE_RE = re.compile(r'^\s*image:\s*"?([^"\s]+@sha256:[0-9a-f]{64})"?\s*$', re.MULTILINE)

# Nearest indent-0 "<key>:" line — the top-level values.yaml section a pin
# lives under, used only as a fallback classification signal for a
# component not present in the render at all (e.g. disabled in the CI
# values).
TOP_LEVEL_KEY_RE = re.compile(r"^([a-zA-Z0-9_-]+):")


def parse_image_ref(ref):
    """ "<repository>[:<version>]@sha256:<digest>" -> (repository, version,
    digest). version is None for a tagless digest reference (a valid k8s
    image ref a vendored sub-chart's helper may emit) — the trailing ":"
    of a "host:port" registry is not a tag either (a real tag has no "/")."""
    repo_and_tag, digest = ref.rsplit("@sha256:", 1)
    repository, sep, version = repo_and_tag.rpartition(":")
    if not sep or "/" in version:
        return repo_and_tag, None, digest
    return repository, version, digest


def dependency_names(chart_dir):
    """Every direct dependency name/alias declared in Chart.yaml (alias
    wins over name when present) — the set classify_by_key checks
    membership against to tell a vendored sub-chart's own top-level key
    apart from a podiumd-owned one."""
    chart_yaml = load_yaml(chart_dir / "Chart.yaml") or {}
    return {values_key_of(dep) for dep in chart_yaml.get("dependencies", [])}


def top_level_key_for_line(lines, line_no):
    """The nearest indent-0 "<key>:" line at or above `line_no` (0-based)
    in `lines`, per TOP_LEVEL_KEY_RE — the top-level values.yaml section a
    given pin lives under, used as classify_by_key's fallback
    classification signal. None if no such line precedes it."""
    for i in range(line_no - 1, -1, -1):
        m = TOP_LEVEL_KEY_RE.match(lines[i])
        if m:
            return m.group(1)
    return None


def classify_source(source, vendor_map):
    """ "own" | a vendor label | "other", from a rendered "# Source:"
    path — same rule check_yamllint/check_kubeconform/etc. use."""
    if source.startswith(OWN_TEMPLATES_PREFIX):
        return "own"
    return vendor_map.get(chart_name_from_source(source), "other")


def classify_by_key(top_level_key, dep_names, vendor_map):
    """Fallback for an image whose component isn't in the render at all:
    "own" if no Chart.yaml dependency has this name/alias (nothing but a
    podiumd-owned template could be configuring it), else the same
    partner/other split as classify_source, keyed by dependency name
    instead of "# Source:" path."""
    if top_level_key not in dep_names:
        return "own"
    return vendor_map.get(top_level_key, "other")


def bucket_of(label):
    """Collapse a classify_source/classify_by_key label into one of the
    three report buckets: "own"/"other" pass through unchanged, and any
    specific vendor label collapses to "partner" — see print_bucket_report's
    own/partner/other split."""
    if label in ("own", "other"):
        return label
    return "partner"


def render_image_labels(rendered_text, vendor_map):
    """(repository, version, digest) -> classification label, for every
    digest-pinned image found in the render. "own" always wins if ANY
    source classifies an image that way, even if another source also
    renders it — this repo's decision to use that image directly in its
    own template outweighs it also being some vendored chart's default."""
    labels = {}
    for source, text in split_rendered_by_source(rendered_text):
        label = classify_source(source, vendor_map)
        for ref in PINNED_IMAGE_RE.findall(text):
            key = parse_image_ref(ref)
            if labels.get(key) != "own":
                labels[key] = label
    return labels


@dataclass
class ImageClassification:
    """rendered_labels/dep_names/vendor_map — render_image_labels/
    classify_by_key's own combined output, from _classify_pinned_
    images, threaded through the per-target scan loop as one unit."""

    rendered_labels: dict
    dep_names: set
    vendor_map: dict


@dataclass
class CveScanSettings:
    """high_severities/package_cve_list_threshold/cve_cache_ttl_days/
    upgrade_cache_ttl_days — check_cves' own 4 lib.settings-derived
    values, resolved once up front and threaded through every helper
    below that needs any subset of them."""

    high_severities: list
    package_cve_list_threshold: int
    cve_cache_ttl_days: int
    upgrade_cache_ttl_days: int


@dataclass
class ScanContext:
    """chart_dir/values_lines/classification/upgrade_cache/session/
    settings — check_cves' own per-run scan inputs, bundled once so the
    per-target loop body (_scan_one_target) doesn't need a dozen
    separate parameters."""

    chart_dir: object
    values_lines: list
    classification: ImageClassification
    upgrade_cache: dict
    session: CacheSession
    settings: CveScanSettings


@dataclass
class ReportSettings:
    """detail_level/high_severities/package_cve_list_threshold —
    print_bucket_report's own per-run settings, identical across all
    three bucket calls in check_cves, bundled since threading 3 more
    positional-only params through every call site is pure repetition."""

    detail_level: str
    high_severities: list
    package_cve_list_threshold: int


@dataclass
class BucketRefs:
    """own/partner/other — check_cves' own three report-bucket ref
    lists (see _bucket_refs), bundled since every consumer below (the
    print calls, the summary/detail lines) needs all three together."""

    own: list
    partner: list
    other: list


@dataclass
class ScanStats:
    """scan_errors/cache_hits/target_count — _scan_all_targets' own
    run-level counters, bundled since the summary-printing/detail-string
    helpers below both need all three together."""

    scan_errors: list
    cache_hits: int
    target_count: int


def _classify_pinned_images(chart_dir, extra_args):
    """An ImageClassification if the chart renders successfully, else
    None (the caller reports "helm template failed to render" and stops)."""
    result = render_chart(chart_dir, extra_args)
    if result.returncode != 0:
        return None
    vendor_map = friendly_vendor_charts(chart_dir)
    dep_names = dependency_names(chart_dir)
    rendered_labels = render_image_labels(result.stdout, vendor_map)
    return ImageClassification(rendered_labels, dep_names, vendor_map)


def _image_ref(repository, version):
    """ "<host>/<repo_path>:<version>" for `repository` — the actual
    pullable ref (never repository's own possibly-stripped/ACR-mirror-
    slug form) trivy/docker needs."""
    host, repo_path = parse_repo(repository)
    return f"{host}/{repo_path}:{version}"


def _target_label(repository, version, digest, line, context):
    """ "own" | a vendor label | "other" for one scan target — the
    render-based classification (see render_image_labels) when the
    image was actually seen in the render, else classify_by_key's own
    values.yaml top-level-key fallback."""
    label = context.classification.rendered_labels.get((repository, version, digest))
    if label is not None:
        return label
    top_key = top_level_key_for_line(context.values_lines, line)
    return classify_by_key(top_key, context.classification.dep_names, context.classification.vendor_map)


def _upgradable_to(repository, version, context):
    """The newer tag lib.image.upgrade_check's own cache reports for
    this (repository, version), or None if there's no fresh entry, or
    the freshest known tag IS the one already pinned."""
    upgrade_entry = context.upgrade_cache.get(upgrade_cache_key(repository, version))
    if (
        upgrade_entry
        and upgrade_entry_is_fresh(upgrade_entry, context.settings.upgrade_cache_ttl_days)
        and upgrade_entry["newest"] != version
    ):
        return upgrade_entry["newest"]
    return None


def _scan_one_target(repo_version, digest_line, index, total, context):
    """(image_ref, entry, was_cached) for one (repository, version)
    target — entry is None when trivy's own scan failed (the caller
    reports image_ref as a scan error and skips it), otherwise the dict
    check_cves' own `images` map stores under image_ref."""
    repository, version = repo_version
    digest, line = digest_line
    image_ref = _image_ref(repository, version)
    label = _target_label(repository, version, digest, line, context)

    # Per-image cache-hit/fresh-scan reporting and the actual cache
    # read/write/scan is the exact same logic lib.checks.cve_diff's
    # own current/proposed scans need — see scan_cached's own
    # docstring for why this is shared rather than reimplemented here.
    vulns, was_cached = scan_cached(
        context.chart_dir,
        ScanTarget(repository, digest, image_ref),
        context.session,
        context.settings.cve_cache_ttl_days,
        label=f"[{index}/{total}] this image",
    )
    if vulns is None:
        return image_ref, None, False

    entry = {
        "bucket": bucket_of(label),
        "vendor_label": label if bucket_of(label) == "partner" else None,
        "vulns": vulns,
        "upgradable_to": _upgradable_to(repository, version, context),
    }
    return image_ref, entry, was_cached


def _scan_all_targets(targets, context):
    """(images, ScanStats) — scan every target in `targets` (see
    _scan_one_target), printing progress/scan-error lines as it goes."""
    print(
        f"Scanning {len(targets)} unique pinned image(s) for known CVEs with trivy "
        f"(pulls every image not already cached — this can take a while)..."
    )
    images, scan_errors, cache_hits = {}, [], 0
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


def _bucket_refs(images):
    """(own_refs, partner_refs, other_refs) — refs (in images' own
    insertion order) whose bucket matches and that have at least one
    vulnerability finding, one list per report bucket."""

    def refs_in(bucket):
        return [ref for ref, info in images.items() if info["bucket"] == bucket and info["vulns"]]

    return refs_in("own"), refs_in("partner"), refs_in("other")


def _print_bucket_reports(images, buckets, report_settings):
    print_bucket_report("Own images", buckets.own, images, report_settings)
    print_bucket_report("Partner-vendor images", buckets.partner, images, report_settings)
    print_bucket_report("Other-vendor images", buckets.other, images, report_settings)


def _print_cve_summary_lines(buckets, stats, cve_cache_ttl_days):
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


def _cve_summary_detail(buckets, images, stats):
    """The final "CVEs: ... own (... img), ... partner-vendor (... img),
    ... other-vendor (... img); ... scan error(s)" detail string
    check_cves returns for verify-podiumd's own summary line."""
    own_n, own_cve = bucket_totals(buckets.own, images)
    partner_n, partner_cve = bucket_totals(buckets.partner, images)
    other_n, other_cve = bucket_totals(buckets.other, images)
    return (
        f"CVEs: {own_cve} own ({own_n} img), {partner_cve} partner-vendor ({partner_n} img), "
        f"{other_cve} other-vendor ({other_n} img); {len(stats.scan_errors)} scan error(s)"
    )


def check_cves(chart_dir, extra_args, detail=False):
    """Entry point for the "CVE scan" step (see module docstring for the
    full design). Renders the chart to classify every unique digest-pinned
    image as own/partner-vendor/other-vendor, scans each one with trivy
    (via scan_cached, reusing cve-scan-cache.json across runs), and prints
    a per-bucket report — full itemization when `detail` is set, otherwise
    per-image severity totals only (see print_bucket_report). Always
    returns True (a CVE finding is never a failing condition here, only a
    triage signal for a human — see module docstring); the detail string
    carries the own/partner/other CVE and image counts plus any scan
    error count for verify-podiumd's own summary line."""
    if shutil.which("docker") is None:
        return True, "docker is not installed — skipped (see --help)"

    settings = CveScanSettings(
        cve_high_severity_levels(chart_dir),
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

    # Not a prune pass: new_cache started as a COPY of old_cache (see
    # open_cache_session), so any entry this run didn't touch — a pin no
    # longer present, or (critically) a lib.checks.cve_diff "proposed"-
    # side entry for an image that's never actually pinned in values.yaml
    # at all — is carried forward untouched here, not deleted. It ages
    # out on its own via cache_entry_is_fresh's own TTL, same as
    # everything else. Real bug this fixes: new_cache used to start
    # EMPTY, so this save wiped out every such entry on nearly every run
    # (check_cves runs right before check_cve_diff in the default
    # pipeline) — cve_diff_check's own already-correct new_cache =
    # dict(old_cache) pattern never had this problem, only this loop did.
    save_cache(chart_dir, session.new_cache)

    buckets = BucketRefs(*_bucket_refs(images))
    report_settings = ReportSettings(
        "full" if detail else "totals", settings.high_severities, settings.package_cve_list_threshold
    )
    _print_bucket_reports(images, buckets, report_settings)
    _print_cve_summary_lines(buckets, stats, settings.cve_cache_ttl_days)

    return True, _cve_summary_detail(buckets, images, stats)


def bucket_totals(refs, images):
    """(image count, total vulnerability count) for one bucket's `refs` —
    the pair check_cves' own final detail string reports per bucket."""
    return len(refs), sum(len(images[ref]["vulns"]) for ref in refs)


def severity_label(severity):
    """Trivy's own "CRITICAL" is the one severity name worth shortening —
    it's both the most common word in a wall of CVE output and the least
    ambiguous to abbreviate."""
    return "CRIT" if severity == "CRITICAL" else severity


def high_findings_by_package(vulns, high_severities):
    """PkgName -> list of its CRITICAL/HIGH vulnerability dicts (see
    cve_scan.high_severity_levels in lib.settings) — the grouping unit for
    print_package_line. A single package/file can carry many CVE IDs (a
    bundled binary like Chromium tracks each fixed CVE separately against
    the same package), so grouping here is what turns a wall of
    near-duplicate lines into one line per actionable upgrade."""
    groups = {}
    for v in vulns:
        if v["Severity"] in high_severities:
            groups.setdefault(v["PkgName"], []).append(v)
    return groups


def print_package_line(pkg, vulns_for_pkg, threshold):
    """Print one "full" detail-level line for `pkg`'s own CRIT/HIGH
    findings (see high_findings_by_package) — every CVE ID listed
    individually (worst severity first) when there are `threshold` (see
    cve_scan.max_cves_per_package_before_summarizing in lib.settings) or
    fewer, otherwise collapsed to a single per-severity count so a
    bundled binary carrying hundreds of tracked CVEs against the same
    package doesn't flood the report with IDs nobody will triage
    individually."""
    # No fix-version shown here, deliberately: a package's FixedVersion is
    # an internal detail of the base image, not something this repo pins
    # or can bump directly — only a newer image tag is actionable, and
    # that's already reported once per image via describe_newest_tag.
    ordered = sorted(vulns_for_pkg, key=lambda v: SEVERITY_ORDER.index(v["Severity"]))

    if len(ordered) <= threshold:
        ids = ", ".join(f"{severity_label(v['Severity'])} {v['VulnerabilityID']}" for v in ordered)
        print(f"  {pkg}: {ids}")
        return

    counts = Counter(v["Severity"] for v in ordered)
    parts = ", ".join(f"{counts[s]} {severity_label(s)}" for s in SEVERITY_ORDER if counts.get(s))
    print(f"  {pkg}: {len(ordered)} CVE(s) ({parts})")


def print_severity_totals_line(vulns):
    """Print one "totals" detail-level line: every severity present in
    `vulns` (including CRIT/HIGH), worst-first per SEVERITY_ORDER, as a
    plain per-severity count — no package breakdown, no individual CVE
    IDs."""
    counts = Counter(v["Severity"] for v in vulns)
    parts = ", ".join(f"{counts[s]} {severity_label(s)}" for s in SEVERITY_ORDER if counts.get(s))
    print(f"  {parts} CVE(s)")


def print_bucket_header(title, empty):
    """Print "--- {title} ---" unless `empty` — the shared "skip a bucket
    with nothing flagged in it entirely, otherwise print its own header"
    idiom every bucketed report in this codebase uses (this module's own
    print_bucket_report below, and lib.checks.cve_diff's own per-bucket
    scan+diff+print loop) — factored out here so there's one place this
    trivial-looking convention lives, not two independently-written
    copies that could silently drift (e.g. one gaining a blank line the
    other doesn't). Returns whether the header was printed, so a caller
    that needs to know (rather than always printing its own body
    unconditionally right after) can branch on it."""
    if empty:
        return False
    print(f"--- {title} ---")
    return True


def print_bucket_report(title, refs, images, settings):
    """`settings` is a ReportSettings; settings.detail_level, applied
    identically regardless of which bucket this is (own/partner-vendor/
    other-vendor all get the same treatment — no aggregate-only rollup
    for other-vendor, unlike every other check that uses this own/
    partner/other scope split):
      "full"   — CRIT/HIGH itemized per affected package (see
                 print_package_line), MEDIUM/LOW/UNKNOWN just totaled per
                 image.
      "totals" — per-image severity totals only (every severity, including
                 CRIT/HIGH) — no package breakdown, no individual CVE IDs."""
    if not print_bucket_header(title, empty=not refs):
        return

    for ref in refs:
        info = images[ref]
        vendor = f" [{info['vendor_label']}]" if info["vendor_label"] else ""
        upgradable = f" upgradable to {info['upgradable_to']}" if info["upgradable_to"] else ""
        print(f"{ref}{vendor}{upgradable}")

        if settings.detail_level == "totals":
            print_severity_totals_line(info["vulns"])
        else:
            rest_counts = Counter(v["Severity"] for v in info["vulns"] if v["Severity"] not in settings.high_severities)
            if rest_counts:
                parts = ", ".join(f"{rest_counts[s]} {s}" for s in ("MEDIUM", "LOW", "UNKNOWN") if rest_counts.get(s))
                print(f"  {parts} CVE(s)")

            for pkg, vulns_for_pkg in sorted(high_findings_by_package(info["vulns"], settings.high_severities).items()):
                print_package_line(pkg, vulns_for_pkg, settings.package_cve_list_threshold)

        print()
