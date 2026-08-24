"""Report-only sweep for known CVEs (with a fix available) against every
digest-pinned image in values.yaml, via a per-image `docker run
aquasec/trivy:latest image` scan — the same tool and invocation shape this
repo already uses to scan images in
.github/workflows/trivy-vuln-scanner.yaml. Companion to check_image_digests
(which only catches the SAME tag's digest moving) and to Renovate (which
lags on niche images per .claude/commands/check-image-cves.md) — this
catches "a newer tag exists with a known fix" regardless of whether the
currently-pinned tag has drifted.

Opt-in only (--check-cves), NOT part of the default run and not in
SKIPPABLE_STEPS: scanning every unique pinned image pulls each one via
Docker and can take several minutes, unlike every other check in this
pipeline. Never fails the check regardless of severity found — a
HIGH/CRITICAL CVE with a fix available is a triage decision for a human
(is the fix actually reachable here, is the severity exploitable in this
deployment, ...), not a chart-correctness fact this script can gate on.

Scan results are cached by (repository, digest) in .cache/cve-scan-cache.json
at the repo root (.cache/ is already gitignored repo-wide — same convention
/helm-docs-check uses for its own binary cache) so a run doesn't re-pull and
re-scan an image whose pin hasn't changed since last time. Keyed on digest,
not version, so a sliding tag republished under the same version string
still invalidates correctly. Capped by CVE_CACHE_TTL_DAYS even for an
unchanged digest — the image content never changes, but trivy's own
vulnerability DB does, so a digest that scanned clean a month ago may have
a newly-disclosed CVE against it today."""
import json
import shutil
from datetime import datetime, timedelta, timezone

from lib.image_digests import scan_digest_pins
from lib.procutil import run
from lib.registry import parse_repo
from lib.render_scope import print_grouped_findings

TRIVY_IMAGE = "aquasec/trivy:latest"
# Trivy's own severities, worst first — anything else (a future severity
# trivy adds) sorts last rather than crashing.
SEVERITY_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN"]

# How long a cached scan result stays valid for an unchanged digest. Long
# enough that a routine run doesn't re-pull/re-scan every image every time;
# short enough that a stale "no findings" cache entry doesn't silently hide
# a CVE disclosed against that digest after it was last scanned.
CVE_CACHE_TTL_DAYS = 7

CACHE_RELATIVE_PATH = (".cache", "cve-scan-cache.json")


def cache_path(chart_dir):
    """.cache/cve-scan-cache.json at the repo root. chart_dir is always
    <repo>/charts/podiumd (this script's own DEFAULT_CHART_DIR), so the
    repo root is two levels up."""
    return chart_dir.parent.parent.joinpath(*CACHE_RELATIVE_PATH)


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
    of vulnerability dicts (VulnerabilityID/PkgName/Severity/FixedVersion/
    Title), or None if trivy's own output couldn't be parsed as JSON (a
    pull failure or trivy crash, not a chart problem)."""
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
        vulns.extend(res.get("Vulnerabilities") or [])
    return vulns


def check_cves(chart_dir):
    if shutil.which("docker") is None:
        return True, "docker is not installed — skipped (see --help)"

    values_path = chart_dir / "values.yaml"
    lines = values_path.read_text(encoding="utf-8").splitlines()
    pins = scan_digest_pins(lines)

    # First digest seen per (repository, version) — same convention as
    # check_image_digests, which assumes every occurrence of a given
    # (repository, version) pin shares one digest.
    targets = {}
    for p in pins:
        if p["repository"]:
            targets.setdefault((p["repository"], p["version"]), p["digest"])
    targets = sorted(targets.items())

    old_cache = load_cache(chart_dir)
    new_cache = {}
    cache_hits = 0

    print(f"Scanning {len(targets)} unique pinned image(s) for known CVEs with trivy "
          f"(pulls every image not already cached — this can take a while)...")

    findings = []
    scan_errors = []
    for (repository, version), digest in targets:
        host, repo_path = parse_repo(repository)
        image_ref = f"{host}/{repo_path}:{version}"
        key = cache_key(repository, digest)
        cached = old_cache.get(key)

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

        for v in vulns:
            severity = v.get("Severity", "UNKNOWN")
            findings.append((image_ref, severity, v.get("VulnerabilityID", "?"),
                              v.get("PkgName", "?"), v.get("FixedVersion", "?")))

    save_cache(chart_dir, new_cache)  # drop entries for images no longer pinned

    def severity_rank(severity):
        return SEVERITY_ORDER.index(severity) if severity in SEVERITY_ORDER else len(SEVERITY_ORDER)

    if findings:
        findings.sort(key=lambda f: (severity_rank(f[1]), f[0]))
        print(f"Found {len(findings)} known CVE(s) with a fix available across "
              f"{len({f[0] for f in findings})} image(s) (report-only, never fails — a "
              f"severity/urgency call for a human to triage):")
        print_grouped_findings(
            findings,
            key_fn=lambda f: f[0],
            item_fn=lambda f: f"{f[1]} {f[2]} ({f[3]} -> {f[4]})",
            label_fn=lambda k: k,
            items_label="CVE(s)",
        )
    else:
        print("OK: no known CVEs with a fix available found across pinned images")

    if scan_errors:
        print(f"{len(scan_errors)} image(s) could not be scanned: {', '.join(scan_errors)}")
    print(f"{cache_hits}/{len(targets)} image(s) served from cache (unchanged digest, "
          f"scanned within the last {CVE_CACHE_TTL_DAYS} days)")

    detail = (f"{len(findings)} CVE(s) across {len(targets)} image(s), {cache_hits} cached, "
              f"{len(scan_errors)} scan error(s)")
    return True, detail
