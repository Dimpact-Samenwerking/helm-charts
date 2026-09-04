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
gets one line listing its CVE IDs, or — past PACKAGE_CVE_LIST_THRESHOLD —
a single summarized count instead of hundreds of IDs nobody will triage
individually. MEDIUM/LOW/UNKNOWN are still only totaled per image, even
with --detail — nothing in this repo can act on those package-by-package
either, so itemizing them would just be noise.

Each image's line also carries an inline "upgradable to X" marker when
lib.image_upgrade_check's own cache (charts/podiumd/image-upgrade-
cache.json, via lib.image_upgrade_cache) has a fresh entry showing a
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
anything) is a separate, standalone check — see lib.image_upgrade_check —
split out from here since the two questions are independent: a newer tag
existing doesn't mean it fixes a given CVE, and that check's answer is
useful even for an image with zero findings here.

Scan results are cached by (repository, digest) in
<repo-root>/.cache/cve-scan-cache.json — a personal, gitignored,
per-checkout cache (see cache_path), not shared between contributors or
CI: each of those re-scans an image the first time they see its digest,
same as a cold cache after cloning fresh. Keyed on digest, not version,
so a sliding tag republished under the same version string still
invalidates correctly. Capped by CVE_CACHE_TTL_DAYS even for an unchanged
digest — the image content never changes, but trivy's own vulnerability
DB does, so a digest that scanned clean a month ago may have a
newly-disclosed CVE against it today. Each cached vulnerability is
trimmed to just the three fields the report actually uses
(VulnerabilityID/PkgName/Severity) — trivy's raw Title/Description/
References/CVSS/dates/FixedVersion would otherwise bloat the cache file
for no reporting benefit. FixedVersion in particular is never shown: this
repo only ever pins a base image tag/digest, never an individual
OS/language package version inside that image, so "upgrade to version X"
for one bundled package isn't an actionable step here — whether a newer
image tag exists at all is lib.image_upgrade_check's job, not this
module's."""
import json
import re
import shutil
from collections import Counter
from datetime import datetime, timedelta, timezone

from lib.chart import load_yaml
from lib.gitutil import find_repo_root
from lib.image_digests import scan_digest_pins
from lib.image_upgrade_cache import cache_entry_is_fresh as upgrade_entry_is_fresh
from lib.image_upgrade_cache import cache_key as upgrade_cache_key
from lib.image_upgrade_cache import load_cache as load_upgrade_cache
from lib.procutil import run
from lib.registry import parse_repo
from lib.render_scope import (
    CHART_NAME, OWN_TEMPLATES_PREFIX, chart_name_from_source, friendly_vendor_charts,
    split_rendered_by_source,
)

TRIVY_IMAGE = "aquasec/trivy:latest"
# Trivy's own severities, worst first — anything else (a future severity
# trivy adds) sorts last rather than crashing.
SEVERITY_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN"]
HIGH_SEVERITIES = {"CRITICAL", "HIGH"}

# Past this many CRITICAL/HIGH CVEs against the SAME package/file, listing
# every ID stops being useful (a bundled binary like gotenberg's Chromium
# can carry hundreds against one package) — summarize as a count instead.
PACKAGE_CVE_LIST_THRESHOLD = 5

# Only these three fields are ever used for reporting — everything else
# trivy returns per vulnerability (Title, Description, References, CVSS
# scores, published/last-modified dates, FixedVersion, ...) is dead weight
# in the cache. FixedVersion is deliberately excluded even though trivy
# reports it: this repo only pins a base image tag/digest, never an
# individual package version inside that image, so it's not information
# this report can act on (see describe_newest_tag for the check that is).
VULN_FIELDS = ("VulnerabilityID", "PkgName", "Severity")

# How long a cached scan result stays valid for an unchanged digest. Long
# enough that a routine run doesn't re-pull/re-scan every image every time;
# short enough that a stale "no findings" cache entry doesn't silently hide
# a CVE disclosed against that digest after it was last scanned.
CVE_CACHE_TTL_DAYS = 7

CACHE_FILENAME = "cve-scan-cache.json"


def cache_path(chart_dir):
    """<repo-root>/.cache/cve-scan-cache.json — a personal, gitignored,
    per-checkout cache (see module docstring), never committed. Rooted at
    the repo root (not chart_dir) so root .gitignore's plain /.cache/
    entry covers it without a chart-specific rule. Falls back to chart_dir
    itself if it isn't inside a git checkout."""
    root = find_repo_root(chart_dir) or chart_dir
    return root / ".cache" / CACHE_FILENAME


def load_cache(chart_dir):
    path = cache_path(chart_dir)
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_cache(chart_dir, cache):
    path = cache_path(chart_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, indent=2, sort_keys=True), encoding="utf-8")


def cache_key(repository, digest):
    return f"{repository}@sha256:{digest}"


def cache_entry_is_fresh(entry):
    try:
        scanned_at = datetime.fromisoformat(entry["scanned_at"])
    except (KeyError, ValueError, TypeError):
        return False
    return datetime.now(timezone.utc) - scanned_at < timedelta(days=CVE_CACHE_TTL_DAYS)


def run_trivy(image_ref):
    """Scan image_ref with trivy (via `docker run`, same shape as this
    repo's own trivy-vuln-scanner.yaml workflow — --ignore-unfixed so only
    vulnerabilities with an actual fix available are returned, matching
    what's relevant to "should we bump this image"). Returns the flat list
    of trimmed vulnerability dicts (see VULN_FIELDS), or None if trivy's
    own output couldn't be parsed as JSON (a pull failure or trivy crash,
    not a chart problem)."""
    result = run(
        ["docker", "run", "--rm", TRIVY_IMAGE, "image", "--ignore-unfixed",
         "--scanners", "vuln", "--format", "json", image_ref],
        capture_output=True, text=True,
    )
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None

    vulns = []
    for res in data.get("Results") or []:
        for v in res.get("Vulnerabilities") or []:
            vulns.append({field: v.get(field, "?") for field in VULN_FIELDS})
    return vulns


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
    """"<repository>[:<version>]@sha256:<digest>" -> (repository, version,
    digest). version is None for a tagless digest reference (a valid k8s
    image ref a vendored sub-chart's helper may emit) — the trailing ":"
    of a "host:port" registry is not a tag either (a real tag has no "/")."""
    repo_and_tag, digest = ref.rsplit("@sha256:", 1)
    repository, sep, version = repo_and_tag.rpartition(":")
    if not sep or "/" in version:
        return repo_and_tag, None, digest
    return repository, version, digest


def dependency_names(chart_dir):
    chart_yaml = load_yaml(chart_dir / "Chart.yaml") or {}
    return {dep.get("alias", dep["name"]) for dep in chart_yaml.get("dependencies", [])}


def top_level_key_for_line(lines, line_no):
    for i in range(line_no - 1, -1, -1):
        m = TOP_LEVEL_KEY_RE.match(lines[i])
        if m:
            return m.group(1)
    return None


def classify_source(source, vendor_map):
    """"own" | a vendor label | "other", from a rendered "# Source:"
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


def check_cves(chart_dir, extra_args, detail=False):
    if shutil.which("docker") is None:
        return True, "docker is not installed — skipped (see --help)"

    result = run(["helm", "template", CHART_NAME, str(chart_dir), *extra_args],
                 capture_output=True, text=True)
    if result.returncode != 0:
        return False, "helm template failed to render"

    vendor_map = friendly_vendor_charts(chart_dir)
    dep_names = dependency_names(chart_dir)
    rendered_labels = render_image_labels(result.stdout, vendor_map)

    values_path = chart_dir / "values.yaml"
    values_lines = values_path.read_text(encoding="utf-8").splitlines()
    pins = scan_digest_pins(values_lines)

    # First (digest, line) seen per (repository, version) — same
    # convention as check_image_digests, which assumes every occurrence of
    # a given (repository, version) pin shares one digest.
    targets = {}
    for p in pins:
        if p["repository"]:
            targets.setdefault((p["repository"], p["version"]), (p["digest"], p["line"]))
    targets = sorted(targets.items())

    old_cache = load_cache(chart_dir)
    new_cache = {}
    cache_hits = 0
    upgrade_cache = load_upgrade_cache(chart_dir)

    print(f"Scanning {len(targets)} unique pinned image(s) for known CVEs with trivy "
          f"(pulls every image not already cached — this can take a while)...")

    images = {}
    scan_errors = []
    for (repository, version), (digest, line) in targets:
        host, repo_path = parse_repo(repository)
        image_ref = f"{host}/{repo_path}:{version}"
        key = cache_key(repository, digest)
        cached = old_cache.get(key)

        label = rendered_labels.get((repository, version, digest))
        if label is None:
            top_key = top_level_key_for_line(values_lines, line)
            label = classify_by_key(top_key, dep_names, vendor_map)

        if cached and cache_entry_is_fresh(cached):
            vulns = cached["vulnerabilities"]
            cache_hits += 1
            new_cache[key] = cached
        else:
            vulns = run_trivy(image_ref)
            if vulns is None:
                scan_errors.append(image_ref)
                print(f"  [SCAN-ERR] {image_ref}  trivy scan failed or produced unparseable output")
                continue
            new_cache[key] = {
                "scanned_at": datetime.now(timezone.utc).isoformat(),
                "vulnerabilities": vulns,
            }
            save_cache(chart_dir, new_cache)  # persist incrementally — this sweep is slow

        upgrade_entry = upgrade_cache.get(upgrade_cache_key(repository, version))
        upgradable_to = None
        if upgrade_entry and upgrade_entry_is_fresh(upgrade_entry) and upgrade_entry["newest"] != version:
            upgradable_to = upgrade_entry["newest"]

        images[image_ref] = {
            "bucket": bucket_of(label),
            "vendor_label": label if bucket_of(label) == "partner" else None,
            "vulns": vulns,
            "upgradable_to": upgradable_to,
        }

    save_cache(chart_dir, new_cache)  # drop entries for images no longer pinned

    def refs_in(bucket):
        return [ref for ref, info in images.items() if info["bucket"] == bucket and info["vulns"]]

    own_refs, partner_refs, other_refs = refs_in("own"), refs_in("partner"), refs_in("other")

    level = "full" if detail else "totals"
    print_bucket_report("Own images", own_refs, images, detail_level=level)
    print_bucket_report("Partner-vendor images", partner_refs, images, detail_level=level)
    print_bucket_report("Other-vendor images", other_refs, images, detail_level=level)

    if not (own_refs or partner_refs or other_refs):
        print("OK: no known CVEs found across pinned images")

    if scan_errors:
        print(f"{len(scan_errors)} image(s) could not be scanned:")
        for ref in scan_errors:
            print(f"  {ref}")
    print(f"{cache_hits}/{len(targets)} image(s) served from cache (unchanged digest, "
          f"scanned within the last {CVE_CACHE_TTL_DAYS} days)")

    own_n, own_cve = bucket_totals(own_refs, images)
    partner_n, partner_cve = bucket_totals(partner_refs, images)
    other_n, other_cve = bucket_totals(other_refs, images)
    detail = (f"CVEs: {own_cve} own ({own_n} img), {partner_cve} partner-vendor ({partner_n} img), "
              f"{other_cve} other-vendor ({other_n} img); {len(scan_errors)} scan error(s)")
    return True, detail


def bucket_totals(refs, images):
    return len(refs), sum(len(images[ref]["vulns"]) for ref in refs)


def severity_label(severity):
    """Trivy's own "CRITICAL" is the one severity name worth shortening —
    it's both the most common word in a wall of CVE output and the least
    ambiguous to abbreviate."""
    return "CRIT" if severity == "CRITICAL" else severity


def high_findings_by_package(vulns):
    """PkgName -> list of its CRITICAL/HIGH vulnerability dicts — the
    grouping unit for print_package_line. A single package/file can carry
    many CVE IDs (a bundled binary like Chromium tracks each fixed CVE
    separately against the same package), so grouping here is what turns a
    wall of near-duplicate lines into one line per actionable upgrade."""
    groups = {}
    for v in vulns:
        if v["Severity"] in HIGH_SEVERITIES:
            groups.setdefault(v["PkgName"], []).append(v)
    return groups


def print_package_line(pkg, vulns_for_pkg):
    # No fix-version shown here, deliberately: a package's FixedVersion is
    # an internal detail of the base image, not something this repo pins
    # or can bump directly — only a newer image tag is actionable, and
    # that's already reported once per image via describe_newest_tag.
    ordered = sorted(vulns_for_pkg, key=lambda v: SEVERITY_ORDER.index(v["Severity"]))

    if len(ordered) <= PACKAGE_CVE_LIST_THRESHOLD:
        ids = ", ".join(f"{severity_label(v['Severity'])} {v['VulnerabilityID']}" for v in ordered)
        print(f"  {pkg}: {ids}")
        return

    counts = Counter(v["Severity"] for v in ordered)
    parts = ", ".join(f"{counts[s]} {severity_label(s)}" for s in SEVERITY_ORDER if counts.get(s))
    print(f"  {pkg}: {len(ordered)} CVE(s) ({parts})")


def print_severity_totals_line(vulns):
    counts = Counter(v["Severity"] for v in vulns)
    parts = ", ".join(f"{counts[s]} {severity_label(s)}" for s in SEVERITY_ORDER if counts.get(s))
    print(f"  {parts} CVE(s)")


def print_bucket_report(title, refs, images, detail_level):
    """detail_level, applied identically regardless of which bucket this is
    (own/partner-vendor/other-vendor all get the same treatment — no
    aggregate-only rollup for other-vendor, unlike every other check that
    uses this own/partner/other scope split):
      "full"   — CRIT/HIGH itemized per affected package (see
                 print_package_line), MEDIUM/LOW/UNKNOWN just totaled per
                 image.
      "totals" — per-image severity totals only (every severity, including
                 CRIT/HIGH) — no package breakdown, no individual CVE IDs."""
    if not refs:
        return
    print(f"--- {title} ---")

    for ref in refs:
        info = images[ref]
        vendor = f" [{info['vendor_label']}]" if info["vendor_label"] else ""
        upgradable = f" upgradable to {info['upgradable_to']}" if info["upgradable_to"] else ""
        print(f"{ref}{vendor}{upgradable}")

        if detail_level == "totals":
            print_severity_totals_line(info["vulns"])
        else:
            rest_counts = Counter(v["Severity"] for v in info["vulns"] if v["Severity"] not in HIGH_SEVERITIES)
            if rest_counts:
                parts = ", ".join(f"{rest_counts[s]} {s}" for s in ("MEDIUM", "LOW", "UNKNOWN") if rest_counts.get(s))
                print(f"  {parts} CVE(s)")

            for pkg, vulns_for_pkg in sorted(high_findings_by_package(info["vulns"]).items()):
                print_package_line(pkg, vulns_for_pkg)

        print()
