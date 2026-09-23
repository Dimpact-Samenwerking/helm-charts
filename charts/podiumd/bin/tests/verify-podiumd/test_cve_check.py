"""run_trivy / check_cves — report-only CVE sweep against every unique
digest-pinned image, via `docker run aquasec/trivy:latest`, split into
own/partner-vendor/other-vendor buckets that ALL get identical treatment
(no aggregate-only rollup for other-vendor). By default every bucket gets
terse per-image severity totals — see check_cves(..., detail=True) for
the opt-in itemized view: CRITICAL/HIGH ("CRIT/HIGH") per image, grouped by
affected package — one line per package listing its CVE IDs, or (past
PACKAGE_CVE_LIST_THRESHOLD) a summarized count instead of every ID — with
MEDIUM/LOW/UNKNOWN still only totaled per image. Cached by (repository,
digest) in <repo-root>/.cache/cve-scan-cache.json — a personal,
gitignored, per-checkout cache, not shared across contributors/CI. No
real docker/trivy/registry invocation happens in
these tests — `run` is mocked throughout. Whether a newer tag is
published at all is lib.image.upgrade_check's job, not this module's —
see tests/verify-podiumd/test_image_upgrade_check.py — but this module
DOES read that check's cache (lib.image.upgrade_cache), read-only, to
annotate a finding as "upgradable"."""

import json

from datetime import datetime
from datetime import timedelta
from datetime import timezone
from types import SimpleNamespace

import pytest


def trivy_result(returncode=0, stdout="", stderr=""):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def vuln(severity, cve="CVE-2024-0001", pkg="openssl", fixed="3.0.2", extra=None):
    d = {"VulnerabilityID": cve, "PkgName": pkg, "Severity": severity, "FixedVersion": fixed}
    if extra:
        d.update(extra)
    return d


CVE_CACHE_TTL_DAYS = 7
HIGH_SEVERITIES = {"CRITICAL", "HIGH"}
PACKAGE_CVE_LIST_THRESHOLD = 5


def trimmed(v):
    return {k: v[k] for k in ("VulnerabilityID", "PkgName", "Severity")}


DIGEST_A = "a" * 64  # own: frankgateway
DIGEST_B = "b" * 64  # partner: openzaak (Maykin)
DIGEST_C = "c" * 64  # other: redis-operator

CHART_YAML = """\
apiVersion: v2
name: podiumd
version: 0.0.1
dependencies:
  - name: openzaak
    version: 1.0.0
    repository: https://maykinmedia.github.io/charts/
  - name: redis-operator
    version: 1.0.0
    repository: https://ot-container-kit.github.io/helm-charts/
"""

VALUES_YAML = (
    "frankgateway:\n"
    "  image:\n"
    "    repository: ghcr.io/wearefrank/frank-gateway\n"
    f'    tag: "104@sha256:{DIGEST_A}"\n'
    "openzaak:\n"
    "  image:\n"
    "    repository: maykinmedia/objects-api\n"
    f'    tag: "1.0.0@sha256:{DIGEST_B}"\n'
    "redis-operator:\n"
    "  image:\n"
    "    repository: docker.io/alpine/k8s\n"
    f'    tag: "1.36.2@sha256:{DIGEST_C}"\n'
)

RENDERED = (
    "---\n"
    "# Source: podiumd/templates/frankgateway.yaml\n"
    "apiVersion: apps/v1\n"
    "kind: Deployment\n"
    "metadata:\n"
    "  name: frankgateway\n"
    "spec:\n"
    "  template:\n"
    "    spec:\n"
    "      containers:\n"
    "        - name: apisix\n"
    f"          image: ghcr.io/wearefrank/frank-gateway:104@sha256:{DIGEST_A}\n"
    "---\n"
    "# Source: podiumd/charts/openzaak/templates/deployment.yaml\n"
    "apiVersion: apps/v1\n"
    "kind: Deployment\n"
    "metadata:\n"
    "  name: openzaak\n"
    "spec:\n"
    "  template:\n"
    "    spec:\n"
    "      containers:\n"
    "        - name: openzaak\n"
    f"          image: maykinmedia/objects-api:1.0.0@sha256:{DIGEST_B}\n"
    "---\n"
    "# Source: podiumd/charts/redis-operator/templates/deployment.yaml\n"
    "apiVersion: apps/v1\n"
    "kind: Deployment\n"
    "metadata:\n"
    "  name: redis-operator\n"
    "spec:\n"
    "  template:\n"
    "    spec:\n"
    "      containers:\n"
    "        - name: redis-operator\n"
    f"          image: docker.io/alpine/k8s:1.36.2@sha256:{DIGEST_C}\n"
)


def make_chart_dir(tmp_path, values=VALUES_YAML, chart_yaml=CHART_YAML):
    (tmp_path / "Chart.yaml").write_text(chart_yaml, encoding="utf-8")
    (tmp_path / "values.yaml").write_text(values, encoding="utf-8")
    return tmp_path


def fake_render_chart(rendered=RENDERED, returncode=0):
    def render_chart(chart_dir, extra_args):
        return SimpleNamespace(returncode=returncode, stdout=rendered, stderr="")

    return render_chart


@pytest.fixture(autouse=True)
def _default_render(libcvecheck, monkeypatch):
    """check_cves now gets its render via lib.render_scope.render_chart
    (chart_dir, extra_args), not a run([...]) call of its own — default
    every test in this file to the standard RENDERED fixture text; a
    test needing different rendered content (or a render failure)
    overrides this via its own monkeypatch.setattr(libcvecheck,
    "render_chart", ...) call."""
    monkeypatch.setattr(libcvecheck, "render_chart", fake_render_chart(RENDERED))


def sequenced_run(trivy_by_image=None, ks_returncode=0):
    """check_cves's own remaining run([...]) calls are ALL "docker"
    (trivy) now (the render moved to render_chart, see _default_render
    above) — one call per check_cves(...) invocation, in target order
    (sorted by (repository, version))."""
    trivy_by_image = trivy_by_image or {}

    def run(cmd, **kwargs):
        image_ref = cmd[-1]
        return trivy_by_image.get(image_ref, trivy_result(stdout="{}", returncode=ks_returncode))

    return run


# --- run_trivy ---


def test_run_trivy_trims_vulnerabilities_to_reporting_fields(libcvecheck, monkeypatch):
    raw = vuln("HIGH", extra={"Title": "some CVE", "References": ["http://example.com"] * 50})
    output = {"Results": [{"Target": "img", "Vulnerabilities": [raw]}]}
    monkeypatch.setattr(libcvecheck, "run", lambda cmd, **kw: trivy_result(stdout=json.dumps(output)))
    assert libcvecheck.run_trivy("org/repo:1.0.0") == [trimmed(raw)]


def test_run_trivy_handles_missing_results_and_vulnerabilities_keys(libcvecheck, monkeypatch):
    monkeypatch.setattr(libcvecheck, "run", lambda cmd, **kw: trivy_result(stdout="{}"))
    assert libcvecheck.run_trivy("org/repo:1.0.0") == []


def test_run_trivy_unparseable_output_returns_none(libcvecheck, monkeypatch):
    monkeypatch.setattr(libcvecheck, "run", lambda cmd, **kw: trivy_result(returncode=1, stderr="pull failed"))
    assert libcvecheck.run_trivy("org/repo:1.0.0") is None


# --- scan_cached (the shared primitive check_cves and lib.checks.cve_diff
# both route through) ---


def test_scan_cached_reports_a_hit_and_never_calls_run_trivy(libcvecheck, tmp_path, monkeypatch, capsys):
    key = libcvecheck.cache_key("org/repo", DIGEST_A)
    cached_entry = {
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "vulnerabilities": [trimmed(vuln("CRITICAL", cve="CVE-CACHED"))],
    }
    old_cache = {key: cached_entry}
    new_cache = {}

    def fail_if_called(ref):
        msg = "a cache hit must never call run_trivy"
        raise AssertionError(msg)

    monkeypatch.setattr(libcvecheck, "run_trivy", fail_if_called)

    vulns, was_cached = libcvecheck.scan_cached(
        tmp_path,
        libcvecheck.ScanTarget("org/repo", DIGEST_A, "org/repo:1.0.0"),
        libcvecheck.CacheSession(old_cache, new_cache),
        CVE_CACHE_TTL_DAYS,
        label="current",
    )

    assert was_cached is True
    assert vulns == cached_entry["vulnerabilities"]
    assert new_cache[key] == cached_entry  # carried forward, so it survives the cache-pruning save
    out = capsys.readouterr().out
    assert "current: served from cache — org/repo:1.0.0" in out


def test_scan_cached_reports_a_fresh_scan_and_writes_the_cache(libcvecheck, tmp_path, monkeypatch, capsys):
    old_cache = {}
    new_cache = {}
    fresh_vulns = [trimmed(vuln("HIGH", cve="CVE-FRESH"))]
    monkeypatch.setattr(libcvecheck, "run_trivy", lambda ref: fresh_vulns)

    vulns, was_cached = libcvecheck.scan_cached(
        tmp_path,
        libcvecheck.ScanTarget("org/repo", DIGEST_A, "org/repo:1.0.0"),
        libcvecheck.CacheSession(old_cache, new_cache),
        CVE_CACHE_TTL_DAYS,
        label="proposed",
    )

    assert was_cached is False
    assert vulns == fresh_vulns
    key = libcvecheck.cache_key("org/repo", DIGEST_A)
    assert new_cache[key]["vulnerabilities"] == fresh_vulns
    assert libcvecheck.load_cache(tmp_path)[key]["vulnerabilities"] == fresh_vulns  # persisted, not just in-memory
    out = capsys.readouterr().out
    assert "proposed: scanning fresh (docker pull + trivy) — org/repo:1.0.0..." in out


def test_scan_cached_stale_entry_is_not_used(libcvecheck, tmp_path, monkeypatch):
    key = libcvecheck.cache_key("org/repo", DIGEST_A)
    stale = datetime.now(timezone.utc) - timedelta(days=CVE_CACHE_TTL_DAYS + 1)
    old_cache = {key: {"scanned_at": stale.isoformat(), "vulnerabilities": [trimmed(vuln("CRITICAL"))]}}
    fresh_vulns = [trimmed(vuln("HIGH", cve="CVE-FRESH"))]
    monkeypatch.setattr(libcvecheck, "run_trivy", lambda ref: fresh_vulns)

    vulns, was_cached = libcvecheck.scan_cached(
        tmp_path,
        libcvecheck.ScanTarget("org/repo", DIGEST_A, "org/repo:1.0.0"),
        libcvecheck.CacheSession(old_cache, {}),
        CVE_CACHE_TTL_DAYS,
    )

    assert was_cached is False
    assert vulns == fresh_vulns


def test_scan_cached_none_digest_skips_the_cache_entirely(libcvecheck, tmp_path, monkeypatch):
    """A digest=None candidate (an unresolved proposed tag, see lib.
    checks.cve_diff._scan_proposed) must go straight to run_trivy — no
    cache read, and no cache write either, since there's no digest to
    key it by."""
    calls = []
    monkeypatch.setattr(libcvecheck, "run_trivy", lambda ref: (calls.append(ref), [])[1])
    new_cache = {}

    vulns, was_cached = libcvecheck.scan_cached(
        tmp_path,
        libcvecheck.ScanTarget("org/repo", None, "org/repo:1.0.0"),
        libcvecheck.CacheSession({}, new_cache),
        CVE_CACHE_TTL_DAYS,
    )

    assert was_cached is False
    assert vulns == []
    assert calls == ["org/repo:1.0.0"]
    assert new_cache == {}


def test_scan_cached_failed_scan_returns_none_and_is_never_cached(libcvecheck, tmp_path, monkeypatch):
    monkeypatch.setattr(libcvecheck, "run_trivy", lambda ref: None)
    new_cache = {}

    vulns, was_cached = libcvecheck.scan_cached(
        tmp_path,
        libcvecheck.ScanTarget("org/repo", DIGEST_A, "org/repo:1.0.0"),
        libcvecheck.CacheSession({}, new_cache),
        CVE_CACHE_TTL_DAYS,
    )

    assert vulns is None
    assert was_cached is False
    assert new_cache == {}


def test_scan_cached_default_label_is_this_image(libcvecheck, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(libcvecheck, "run_trivy", lambda ref: [])
    libcvecheck.scan_cached(
        tmp_path,
        libcvecheck.ScanTarget("org/repo", DIGEST_A, "org/repo:1.0.0"),
        libcvecheck.CacheSession({}, {}),
        CVE_CACHE_TTL_DAYS,
    )
    out = capsys.readouterr().out
    assert "this image: scanning fresh" in out


# --- open_cache_session (the shared "load, then start a correct mutable
# working copy" initializer check_cves and lib.checks.cve_diff both call,
# so there's no second independently-written copy of it left to drift —
# see the real bug that happened once, when check_cves' own copy of this
# step quietly wrote new_cache = {} instead) ---


def test_open_cache_session_new_cache_is_a_separate_copy(libcvecheck, tmp_path):
    key = libcvecheck.cache_key("org/repo", DIGEST_A)
    entry = {"scanned_at": datetime.now(timezone.utc).isoformat(), "vulnerabilities": []}
    libcvecheck.save_cache(tmp_path, {key: entry})

    old_cache, new_cache = libcvecheck.open_cache_session(tmp_path)

    assert old_cache == {key: entry}
    assert new_cache == old_cache
    assert new_cache is not old_cache  # mutating one must never affect the other

    new_cache["org/other@sha256:" + "b" * 64] = {"vulnerabilities": []}
    assert "org/other@sha256:" + "b" * 64 not in old_cache


def test_open_cache_session_empty_when_no_cache_file_exists(libcvecheck, tmp_path):
    old_cache, new_cache = libcvecheck.open_cache_session(tmp_path)
    assert old_cache == {}
    assert new_cache == {}
    assert new_cache is not old_cache


def test_check_cves_routes_through_open_cache_session(vp, libcvecheck, tmp_path, monkeypatch):
    chart_dir = make_chart_dir(tmp_path)
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr(libcvecheck, "run", sequenced_run())

    calls = []
    real_open_cache_session = libcvecheck.open_cache_session

    def spy(chart_dir_arg):
        calls.append(chart_dir_arg)
        return real_open_cache_session(chart_dir_arg)

    monkeypatch.setattr(libcvecheck, "open_cache_session", spy)
    vp.check_cves(chart_dir, [])
    assert calls == [chart_dir]


# --- classification ---


def test_classify_source_own(libcvecheck):
    assert libcvecheck.classify_source("podiumd/templates/frankgateway.yaml", {}) == "own"


def test_classify_source_partner(libcvecheck):
    vendor_map = {"openzaak": "Maykin"}
    assert libcvecheck.classify_source("podiumd/charts/openzaak/templates/deployment.yaml", vendor_map) == "Maykin"


def test_classify_source_other(libcvecheck):
    assert libcvecheck.classify_source("podiumd/charts/redis-operator/templates/deployment.yaml", {}) == "other"


def test_classify_by_key_own_when_not_a_dependency(libcvecheck):
    assert libcvecheck.classify_by_key("frankgateway", {"openzaak"}, {}) == "own"


def test_classify_by_key_partner_when_dependency_and_friendly(libcvecheck):
    assert libcvecheck.classify_by_key("openzaak", {"openzaak"}, {"openzaak": "Maykin"}) == "Maykin"


def test_classify_by_key_other_when_dependency_but_not_friendly(libcvecheck):
    assert libcvecheck.classify_by_key("redis-operator", {"redis-operator"}, {}) == "other"


def test_bucket_of(libcvecheck):
    assert libcvecheck.bucket_of("own") == "own"
    assert libcvecheck.bucket_of("other") == "other"
    assert libcvecheck.bucket_of("Maykin") == "partner"


def test_parse_image_ref(libcvecheck):
    assert libcvecheck.parse_image_ref(f"org/repo:1.0.0@sha256:{DIGEST_A}") == ("org/repo", "1.0.0", DIGEST_A)


def test_parse_image_ref_tagless_digest_reference(libcvecheck):
    """A valid k8s ref with a digest and no :tag (a vendored sub-chart's
    helper may emit one) must return version=None, not raise ValueError on
    the tuple unpack."""
    assert libcvecheck.parse_image_ref(f"ghcr.io/foo/bar@sha256:{DIGEST_A}") == ("ghcr.io/foo/bar", None, DIGEST_A)


def test_parse_image_ref_registry_port_is_not_a_tag(libcvecheck):
    assert libcvecheck.parse_image_ref(f"registry.example.com:5000/foo/bar@sha256:{DIGEST_A}") == (
        "registry.example.com:5000/foo/bar",
        None,
        DIGEST_A,
    )


def test_top_level_key_for_line(libcvecheck):
    lines = ["frankgateway:", "  image:", "    tag: x", "openzaak:", "  image:", "    tag: y"]
    assert libcvecheck.top_level_key_for_line(lines, 3) == "frankgateway"
    assert libcvecheck.top_level_key_for_line(lines, 6) == "openzaak"


def test_render_image_labels_own_wins_over_other_sources(libcvecheck):
    """The same image rendered by both an own template and a vendored
    chart must classify as "own" — this repo's own decision to use that
    image directly outweighs it also being some dependency's default."""
    rendered = (
        f"---\n# Source: podiumd/templates/foo.yaml\napiVersion: v1\nkind: Pod\nmetadata:\n  name: a\n"
        f"spec:\n  containers:\n    - name: a\n      image: shared/img:1.0@sha256:{DIGEST_A}\n"
        f"---\n# Source: podiumd/charts/other/templates/bar.yaml\napiVersion: v1\nkind: Pod\nmetadata:\n  name: b\n"
        f"spec:\n  containers:\n    - name: b\n      image: shared/img:1.0@sha256:{DIGEST_A}\n"
    )
    labels = libcvecheck.render_image_labels(rendered, {})
    assert labels[("shared/img", "1.0", DIGEST_A)] == "own"


# --- per-package grouping/summarization ---


def test_severity_label_abbreviates_critical(libcvecheck):
    assert libcvecheck.severity_label("CRITICAL") == "CRIT"
    assert libcvecheck.severity_label("HIGH") == "HIGH"


def test_high_findings_by_package_groups_and_excludes_low_severity(libcvecheck):
    vulns = [
        vuln("CRITICAL", cve="CVE-1", pkg="chromium"),
        vuln("HIGH", cve="CVE-2", pkg="chromium"),
        vuln("HIGH", cve="CVE-3", pkg="openssl"),
        vuln("LOW", cve="CVE-4", pkg="chromium"),
    ]
    groups = libcvecheck.high_findings_by_package(vulns, HIGH_SEVERITIES)
    assert {v["VulnerabilityID"] for v in groups["chromium"]} == {"CVE-1", "CVE-2"}
    assert {v["VulnerabilityID"] for v in groups["openssl"]} == {"CVE-3"}


def test_print_package_line_lists_ids_below_threshold(libcvecheck, capsys):
    vulns_for_pkg = [vuln("CRITICAL", cve="CVE-1"), vuln("HIGH", cve="CVE-2")]
    libcvecheck.print_package_line("libwebp", vulns_for_pkg, PACKAGE_CVE_LIST_THRESHOLD)
    out = capsys.readouterr().out
    assert "libwebp: CRIT CVE-1, HIGH CVE-2" in out


def test_print_package_line_summarizes_above_threshold(libcvecheck, capsys):
    threshold = PACKAGE_CVE_LIST_THRESHOLD
    vulns_for_pkg = [vuln("CRITICAL", cve=f"CVE-{i}") for i in range(threshold + 1)]
    libcvecheck.print_package_line("chromium", vulns_for_pkg, threshold)
    out = capsys.readouterr().out
    assert f"chromium: {threshold + 1} CVE(s) ({threshold + 1} CRIT)" in out


def test_print_package_line_never_shows_fix_version(libcvecheck, capsys):
    """FixedVersion is an internal detail of the base image (an OS/language
    package version), not something this repo pins or can bump directly —
    whether a newer image tag exists at all is lib.image.upgrade_check's
    job, not this one's. A distro package patched across many piecemeal
    security advisories (e.g. Debian's bind9-dnsutils) can carry a wildly
    different FixedVersion per CVE, which is exactly why showing any of
    them here would be both noisy and misleading."""
    vulns_for_pkg = [
        vuln("HIGH", cve="CVE-1", fixed="1:9.16.42-1~deb11u1"),
        vuln("HIGH", cve="CVE-2", fixed="1:9.16.50-1~deb11u6"),
        vuln("HIGH", cve="CVE-3", fixed="1:9.16.48-1"),
    ]
    libcvecheck.print_package_line("bind9-dnsutils", vulns_for_pkg, PACKAGE_CVE_LIST_THRESHOLD)
    out = capsys.readouterr().out
    assert "bind9-dnsutils: HIGH CVE-1, HIGH CVE-2, HIGH CVE-3" in out
    assert "9.16" not in out
    assert "->" not in out


# --- check_cves: docker/render preconditions ---


def test_check_cves_no_docker_passes_and_skips(vp, tmp_path, monkeypatch):
    chart_dir = make_chart_dir(tmp_path)
    monkeypatch.setattr(vp.shutil, "which", lambda name: None)
    ok, detail = vp.check_cves(chart_dir, [])
    assert ok is True
    assert "not installed" in detail


def test_check_cves_render_failure_fails(vp, libcvecheck, tmp_path, monkeypatch):
    chart_dir = make_chart_dir(tmp_path)
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr(libcvecheck, "render_chart", fake_render_chart("", returncode=1))
    ok, detail = vp.check_cves(chart_dir, [])
    assert ok is False
    assert "failed to render" in detail


# --- check_cves: full own/partner/other integration ---


def test_check_cves_splits_own_partner_other_and_never_fails(vp, libcvecheck, tmp_path, monkeypatch, capsys):
    chart_dir = make_chart_dir(tmp_path)
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/docker")

    trivy_by_image = {
        "ghcr.io/wearefrank/frank-gateway:104": trivy_result(
            stdout=json.dumps(
                {"Results": [{"Vulnerabilities": [vuln("CRITICAL", cve="CVE-OWN-1"), vuln("LOW", cve="CVE-OWN-2")]}]}
            )
        ),
        "docker.io/maykinmedia/objects-api:1.0.0": trivy_result(
            stdout=json.dumps({"Results": [{"Vulnerabilities": [vuln("HIGH", cve="CVE-PARTNER-1")]}]})
        ),
        "docker.io/alpine/k8s:1.36.2": trivy_result(
            stdout=json.dumps(
                {
                    "Results": [
                        {"Vulnerabilities": [vuln("CRITICAL", cve="CVE-OTHER-1"), vuln("MEDIUM", cve="CVE-OTHER-2")]}
                    ]
                }
            )
        ),
    }
    monkeypatch.setattr(libcvecheck, "run", sequenced_run(trivy_by_image=trivy_by_image))

    ok, detail = vp.check_cves(chart_dir, [])
    assert ok is True  # never fails regardless of severity
    assert detail == ("CVEs: 2 own (1 img), 1 partner-vendor (1 img), 2 other-vendor (1 img); 0 scan error(s)")

    out = capsys.readouterr().out
    assert "--- Own images ---" in out
    assert "1 CRIT, 1 LOW CVE(s)" in out  # own: per-image totals only by default, same as partner
    assert "CVE-OWN-1" not in out and "CVE-OWN-2" not in out

    assert "--- Partner-vendor images ---" in out
    assert "[Maykin]" in out
    assert "1 HIGH CVE(s)" in out  # partner: per-image totals only, even for HIGH
    assert "CVE-PARTNER-1" not in out  # partner never itemizes individual CVE IDs

    assert "--- Other-vendor images ---" in out
    assert "1 CRIT, 1 MEDIUM CVE(s)" in out  # other-vendor: identical treatment to own/partner now
    assert "CVE-OTHER-1" not in out  # totals only by default, no individual CVE IDs

    # a per-image progress line for each of the 3 (uncached) scans, so a
    # slow trivy pull doesn't look like the step hung -- same "this
    # image: scanning fresh (docker pull + trivy) -- <ref>..." wording
    # lib.checks.cve_diff's own current/proposed lines use, via the same
    # shared lib.checks.cve.scan_cached.
    scan_lines = [line for line in out.splitlines() if "scanning fresh" in line and "docker pull + trivy" in line]
    assert len(scan_lines) == 3
    assert any(line.startswith("  [1/3] this image: scanning fresh ") for line in scan_lines)
    assert any(line.startswith("  [3/3] this image: scanning fresh ") for line in scan_lines)


def test_check_cves_marks_upgradable_from_image_upgrade_cache(
    vp,
    libcvecheck,
    libimageupgradecache,
    tmp_path,
    monkeypatch,
    capsys,
):
    """check_cves reads lib.image.upgrade_check's own cache (read-only, no
    registry call of its own) to append " upgradable to X" after an
    image's name when that cache has a fresh entry showing a newer tag —
    here only frankgateway (own) does; openzaak (partner) has no cache
    entry at all (never checked, or checked-and-stale), so no marker."""
    chart_dir = make_chart_dir(tmp_path)
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/docker")

    libimageupgradecache.save_cache(
        chart_dir,
        {
            libimageupgradecache.cache_key("ghcr.io/wearefrank/frank-gateway", "104"): {
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "newest": "105",
            },
        },
    )

    trivy_by_image = {
        "ghcr.io/wearefrank/frank-gateway:104": trivy_result(
            stdout=json.dumps({"Results": [{"Vulnerabilities": [vuln("CRITICAL", cve="CVE-OWN-1")]}]})
        ),
        "docker.io/maykinmedia/objects-api:1.0.0": trivy_result(
            stdout=json.dumps({"Results": [{"Vulnerabilities": [vuln("HIGH", cve="CVE-PARTNER-1")]}]})
        ),
    }
    monkeypatch.setattr(libcvecheck, "run", sequenced_run(trivy_by_image=trivy_by_image))

    ok, _detail = vp.check_cves(chart_dir, [])
    assert ok is True

    out = capsys.readouterr().out
    assert "ghcr.io/wearefrank/frank-gateway:104 upgradable to 105" in out
    assert "docker.io/maykinmedia/objects-api:1.0.0 [Maykin]\n" in out  # no marker: no cache entry


def test_check_cves_stale_upgrade_cache_entry_not_marked_upgradable(
    vp,
    libcvecheck,
    libimageupgradecache,
    tmp_path,
    monkeypatch,
    capsys,
):
    """A stale (past image_upgrade_check.tag_check_cache_ttl_days) entry
    must not be treated as evidence of an upgrade — cve_check never
    refreshes this cache itself, so a stale entry is as good as no
    entry."""
    chart_dir = make_chart_dir(tmp_path)
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/docker")

    stale = datetime.now(timezone.utc) - timedelta(days=1 + 1)
    libimageupgradecache.save_cache(
        chart_dir,
        {
            libimageupgradecache.cache_key("ghcr.io/wearefrank/frank-gateway", "104"): {
                "checked_at": stale.isoformat(),
                "newest": "105",
            },
        },
    )

    trivy_by_image = {
        "ghcr.io/wearefrank/frank-gateway:104": trivy_result(
            stdout=json.dumps({"Results": [{"Vulnerabilities": [vuln("CRITICAL", cve="CVE-OWN-1")]}]})
        ),
    }
    monkeypatch.setattr(libcvecheck, "run", sequenced_run(trivy_by_image=trivy_by_image))

    ok, _detail = vp.check_cves(chart_dir, [])
    assert ok is True
    out = capsys.readouterr().out
    assert "upgradable" not in out


def test_check_cves_detail_itemizes_every_bucket(vp, libcvecheck, tmp_path, monkeypatch, capsys):
    """--detail (detail=True) elevates ALL THREE buckets — including
    other-vendor, which otherwise never gets per-image detail at all — to
    the full itemized CRIT/HIGH-per-package view."""
    chart_dir = make_chart_dir(tmp_path)
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/docker")

    trivy_by_image = {
        "ghcr.io/wearefrank/frank-gateway:104": trivy_result(
            stdout=json.dumps(
                {"Results": [{"Vulnerabilities": [vuln("CRITICAL", cve="CVE-OWN-1"), vuln("LOW", cve="CVE-OWN-2")]}]}
            )
        ),
        "docker.io/maykinmedia/objects-api:1.0.0": trivy_result(
            stdout=json.dumps({"Results": [{"Vulnerabilities": [vuln("HIGH", cve="CVE-PARTNER-1", pkg="curl")]}]})
        ),
        "docker.io/alpine/k8s:1.36.2": trivy_result(
            stdout=json.dumps(
                {
                    "Results": [
                        {
                            "Vulnerabilities": [
                                vuln("CRITICAL", cve="CVE-OTHER-1", pkg="busybox"),
                                vuln("MEDIUM", cve="CVE-OTHER-2"),
                            ]
                        }
                    ]
                }
            )
        ),
    }
    monkeypatch.setattr(libcvecheck, "run", sequenced_run(trivy_by_image=trivy_by_image))

    ok, _detail = vp.check_cves(chart_dir, [], detail=True)
    assert ok is True

    out = capsys.readouterr().out
    assert "CRIT CVE-OWN-1" in out and "CVE-OWN-2" not in out  # own: itemized, LOW only totaled
    assert "curl: HIGH CVE-PARTNER-1" in out  # partner: now itemized too
    assert "busybox: CRIT CVE-OTHER-1" in out  # other-vendor: now itemized too
    assert "1 MEDIUM CVE(s)" in out  # other-vendor's MEDIUM still only totaled, even with --detail


def test_print_bucket_report_image_line_then_totals_then_packages(libcvecheck, monkeypatch, capsys):
    """Layout, top to bottom, for an itemized image: the image name+vendor
    (+ "upgradable to X" marker, if set) line, then the MEDIUM/LOW/UNKNOWN
    total (if any), then the per-package CRIT/HIGH lines."""
    images = {
        "docker.io/pravega/zookeeper:0.2.15": {
            "bucket": "own",
            "vendor_label": None,
            "upgradable_to": "0.2.16",
            "vulns": [
                vuln("HIGH", cve="CVE-1", pkg="bind9-dnsutils"),
                vuln("MEDIUM", cve="CVE-2"),
                vuln("LOW", cve="CVE-3"),
            ],
        },
    }
    libcvecheck.print_bucket_report(
        "Own images",
        ["docker.io/pravega/zookeeper:0.2.15"],
        images,
        libcvecheck.ReportSettings("full", HIGH_SEVERITIES, PACKAGE_CVE_LIST_THRESHOLD),
    )

    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    header_idx = next(i for i, line in enumerate(lines) if line.startswith("docker.io/pravega/zookeeper:0.2.15"))
    assert lines[header_idx] == "docker.io/pravega/zookeeper:0.2.15 upgradable to 0.2.16"
    assert "1 MEDIUM, 1 LOW CVE(s)" in lines[header_idx + 1]
    assert "bind9-dnsutils: HIGH CVE-1" in lines[header_idx + 2]


def test_print_bucket_report_totals_mode_never_itemizes_even_high_severity(libcvecheck, monkeypatch, capsys):
    """Partner-vendor images (detail_level="totals") get a single per-image
    severity-totals line, covering every severity including CRIT/HIGH — no
    package breakdown, no individual CVE IDs, unlike detail_level="full".
    Not upgradable here, so no marker."""
    images = {
        "docker.io/maykinmedia/objects-api:1.0.0": {
            "bucket": "partner",
            "vendor_label": "Maykin",
            "upgradable_to": None,
            "vulns": [
                vuln("CRITICAL", cve="CVE-1", pkg="openssl"),
                vuln("HIGH", cve="CVE-2", pkg="openssl"),
                vuln("MEDIUM", cve="CVE-3"),
            ],
        },
    }
    libcvecheck.print_bucket_report(
        "Partner-vendor images",
        ["docker.io/maykinmedia/objects-api:1.0.0"],
        images,
        libcvecheck.ReportSettings("totals", HIGH_SEVERITIES, PACKAGE_CVE_LIST_THRESHOLD),
    )

    out = capsys.readouterr().out
    assert "docker.io/maykinmedia/objects-api:1.0.0 [Maykin]\n" in out
    assert "upgradable" not in out
    assert "1 CRIT, 1 HIGH, 1 MEDIUM CVE(s)" in out
    assert "CVE-1" not in out and "CVE-2" not in out and "CVE-3" not in out
    assert "openssl" not in out


def test_check_cves_no_findings_passes(vp, libcvecheck, tmp_path, monkeypatch, capsys):
    chart_dir = make_chart_dir(tmp_path)
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr(libcvecheck, "run", sequenced_run())

    ok, detail = vp.check_cves(chart_dir, [])
    assert ok is True
    assert "0 own (0 img)" in detail
    out = capsys.readouterr().out
    assert "OK: no known CVEs" in out


def test_check_cves_scan_error_reported_but_still_passes(vp, libcvecheck, tmp_path, monkeypatch, capsys):
    chart_dir = make_chart_dir(tmp_path)
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/docker")
    trivy_by_image = {"ghcr.io/wearefrank/frank-gateway:104": trivy_result(returncode=1, stdout="not json")}
    monkeypatch.setattr(libcvecheck, "run", sequenced_run(trivy_by_image=trivy_by_image))

    ok, detail = vp.check_cves(chart_dir, [])
    assert ok is True
    assert "1 scan error(s)" in detail
    out = capsys.readouterr().out
    assert "SCAN-ERR" in out
    assert "could not be scanned:\n  ghcr.io/wearefrank/frank-gateway:104" in out


def test_check_cves_heuristic_fallback_for_disabled_component(vp, libcvecheck, tmp_path, monkeypatch, capsys):
    """A pin whose component isn't in the render at all (e.g. disabled in
    the CI values) falls back to the values-key heuristic: not a
    Chart.yaml dependency -> own."""
    values = VALUES_YAML + (f'apiproxy:\n  image:\n    repository: org/apiproxy\n    tag: "1.0.0@sha256:{"d" * 64}"\n')
    chart_dir = make_chart_dir(tmp_path, values=values)
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/docker")

    trivy_by_image = {
        "docker.io/org/apiproxy:1.0.0": trivy_result(
            stdout=json.dumps({"Results": [{"Vulnerabilities": [vuln("HIGH", cve="CVE-APIPROXY")]}]})
        ),
    }
    monkeypatch.setattr(libcvecheck, "run", sequenced_run(trivy_by_image=trivy_by_image))

    ok, detail = vp.check_cves(chart_dir, [])
    assert ok is True
    # Only apiproxy has findings here (frankgateway/openzaak/redis-operator score
    # clean in this test) — the point is it lands in "own" via the heuristic
    # fallback (not a Chart.yaml dependency), not that it's rendered at all.
    assert "1 own (1 img)" in detail
    out = capsys.readouterr().out
    assert "docker.io/org/apiproxy:1.0.0" in out
    assert "1 HIGH CVE(s)" in out  # own: per-image totals by default, no CVE ID itemized
    assert "CVE-APIPROXY" not in out


# --- caching ---


def test_check_cves_cache_miss_scans_and_persists(vp, libcvecheck, tmp_path, monkeypatch):
    chart_dir = make_chart_dir(tmp_path)
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr(libcvecheck, "run", sequenced_run())

    ok, _detail = vp.check_cves(chart_dir, [])
    assert ok is True
    saved = libcvecheck.load_cache(chart_dir)
    assert libcvecheck.cache_key("ghcr.io/wearefrank/frank-gateway", DIGEST_A) in saved


def test_check_cves_cache_hit_skips_scanning(vp, libcvecheck, tmp_path, monkeypatch, capsys):
    chart_dir = make_chart_dir(tmp_path)
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/docker")
    key = libcvecheck.cache_key("ghcr.io/wearefrank/frank-gateway", DIGEST_A)
    libcvecheck.save_cache(
        chart_dir,
        {
            key: {
                "scanned_at": datetime.now(timezone.utc).isoformat(),
                "vulnerabilities": [trimmed(vuln("CRITICAL", cve="CVE-CACHED"))],
            },
        },
    )

    def fail_if_scanned(cmd, **kw):
        if "frank-gateway" in cmd[-1]:
            msg = "frank-gateway should have been served from cache"
            raise AssertionError(msg)
        return trivy_result(stdout="{}")

    monkeypatch.setattr(libcvecheck, "run", fail_if_scanned)
    ok, _detail = vp.check_cves(chart_dir, [])
    assert ok is True
    out = capsys.readouterr().out
    assert "1 CRIT CVE(s)" in out  # own: per-image totals by default, no CVE ID itemized
    assert "CVE-CACHED" not in out
    assert "1/3 image(s) served from cache" in out
    assert "frank-gateway" not in "".join(line for line in out.splitlines() if "scanning" in line)


def test_check_cves_expired_cache_entry_rescans(vp, libcvecheck, tmp_path, monkeypatch, capsys):
    chart_dir = make_chart_dir(tmp_path)
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/docker")
    key = libcvecheck.cache_key("ghcr.io/wearefrank/frank-gateway", DIGEST_A)
    stale = datetime.now(timezone.utc) - timedelta(days=CVE_CACHE_TTL_DAYS + 1)
    libcvecheck.save_cache(
        chart_dir,
        {
            key: {"scanned_at": stale.isoformat(), "vulnerabilities": [trimmed(vuln("CRITICAL"))]},
        },
    )
    monkeypatch.setattr(libcvecheck, "run", sequenced_run())  # fresh scans find nothing

    ok, detail = vp.check_cves(chart_dir, [])
    assert ok is True
    assert "0 own (0 img)" in detail  # stale finding replaced by the fresh (empty) result
    out = capsys.readouterr().out
    assert "0/3 image(s) served from cache" in out  # expired entry does not count as a hit


def test_check_cves_preserves_entries_for_unpinned_images(vp, libcvecheck, tmp_path, monkeypatch):
    """Regression test (real bug): check_cves used to start new_cache as
    an EMPTY dict, so its own end-of-run save_cache wiped out every
    cache entry this run didn't itself touch -- including a lib.checks.
    cve_diff "proposed"-side entry for an image that's never
    actually pinned in values.yaml at all (a candidate/upgrade tag or a
    slid digest). Since check_cves runs right before check_cve_diff in
    the default pipeline, this destroyed cve-diff's own proposed-side
    cache on nearly every run. new_cache now starts as a COPY of old_
    cache (matching lib.checks.cve_diff's own already-correct pattern),
    so an untouched entry is carried forward as-is and ages out on its
    own TTL, never actively deleted just for not being a current target."""
    chart_dir = make_chart_dir(tmp_path)
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/docker")
    unrelated_key = "org/proposed-candidate@sha256:" + "e" * 64
    unrelated_entry = {
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "vulnerabilities": [trimmed(vuln("CRITICAL", cve="CVE-PROPOSED"))],
    }
    libcvecheck.save_cache(chart_dir, {unrelated_key: unrelated_entry})
    monkeypatch.setattr(libcvecheck, "run", sequenced_run())

    vp.check_cves(chart_dir, [])
    saved = libcvecheck.load_cache(chart_dir)
    assert saved[unrelated_key] == unrelated_entry


def test_check_cves_still_updates_its_own_currently_pinned_targets(vp, libcvecheck, tmp_path, monkeypatch, capsys):
    """new_cache starting as a copy of old_cache must not stop check_cves
    from adding/refreshing entries for its own actual targets exactly as
    before -- only entries it doesn't touch are now preserved rather than
    dropped, nothing about its own targets' own read/write path changed."""
    chart_dir = make_chart_dir(tmp_path)
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr(libcvecheck, "run", sequenced_run())

    ok, _detail = vp.check_cves(chart_dir, [])
    assert ok is True
    saved = libcvecheck.load_cache(chart_dir)
    assert libcvecheck.cache_key("ghcr.io/wearefrank/frank-gateway", DIGEST_A) in saved
