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
deployment, ...), not a chart-correctness fact this script can gate on."""
import json
import shutil

from lib.image_digests import scan_digest_pins
from lib.procutil import run
from lib.registry import parse_repo
from lib.render_scope import print_grouped_findings

TRIVY_IMAGE = "aquasec/trivy:latest"
# Trivy's own severities, worst first — anything else (a future severity
# trivy adds) sorts last rather than crashing.
SEVERITY_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN"]


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

    targets = sorted({(p["repository"], p["version"]) for p in pins if p["repository"]})
    print(f"Scanning {len(targets)} unique pinned image(s) for known CVEs with trivy "
          f"(pulls every image — this can take a while)...")

    findings = []
    scan_errors = []
    for repository, version in targets:
        host, repo_path = parse_repo(repository)
        image_ref = f"{host}/{repo_path}:{version}"
        vulns = run_trivy(image_ref)
        if vulns is None:
            scan_errors.append(image_ref)
            print(f"  [SCAN-ERR] {image_ref}  trivy scan failed or produced unparseable output")
            continue
        for v in vulns:
            severity = v.get("Severity", "UNKNOWN")
            findings.append((image_ref, severity, v.get("VulnerabilityID", "?"),
                              v.get("PkgName", "?"), v.get("FixedVersion", "?")))

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

    detail = f"{len(findings)} CVE(s) across {len(targets)} image(s), {len(scan_errors)} scan error(s)"
    return True, detail
