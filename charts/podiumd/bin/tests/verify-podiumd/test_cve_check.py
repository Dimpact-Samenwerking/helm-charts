"""Tests for run_trivy / check_cves: report-only CVE sweep of digest-pinned images.

Images are split into own/partner-vendor/other-vendor buckets with identical
treatment; `run` is mocked throughout, so no docker/trivy/registry call happens.
The image-upgrade cache is read (read-only) to annotate "upgradable" findings."""

import json

from datetime import datetime
from datetime import timedelta
from datetime import timezone
from pathlib import Path
from types import ModuleType
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


def make_chart_dir(tmp_path: Path, values=VALUES_YAML, chart_yaml=CHART_YAML):
    (tmp_path / "Chart.yaml").write_text(chart_yaml, encoding="utf-8")
    (tmp_path / "values.yaml").write_text(values, encoding="utf-8")
    return tmp_path


def fake_render_chart(rendered=RENDERED, returncode=0):
    def render_chart(chart_dir, extra_args):
        return SimpleNamespace(returncode=returncode, stdout=rendered, stderr="")

    return render_chart


@pytest.fixture(autouse=True)
def _default_render(libcvecheck: ModuleType, monkeypatch: pytest.MonkeyPatch):
    """Default every test to the RENDERED fixture; override render_chart to change it."""
    monkeypatch.setattr(libcvecheck, "render_chart", fake_render_chart(RENDERED))


def sequenced_run(trivy_by_image=None, ks_returncode=0):
    """Fake run() for trivy calls, keyed by image ref."""
    trivy_by_image = trivy_by_image or {}

    def run(cmd, **kwargs):
        image_ref = cmd[-1]
        return trivy_by_image.get(image_ref, trivy_result(stdout="{}", returncode=ks_returncode))

    return run


# --- run_trivy ---


def test_run_trivy_trims_vulnerabilities_to_reporting_fields(libcvecheck: ModuleType, monkeypatch: pytest.MonkeyPatch):
    raw = vuln("HIGH", extra={"Title": "some CVE", "References": ["http://example.com"] * 50})
    output = {"Results": [{"Target": "img", "Vulnerabilities": [raw]}]}
    monkeypatch.setattr(libcvecheck, "run", lambda cmd, **kw: trivy_result(stdout=json.dumps(output)))
    assert libcvecheck.run_trivy("org/repo:1.0.0") == [trimmed(raw)]


def test_run_trivy_handles_missing_results_and_vulnerabilities_keys(
    libcvecheck: ModuleType, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(libcvecheck, "run", lambda cmd, **kw: trivy_result(stdout="{}"))
    assert libcvecheck.run_trivy("org/repo:1.0.0") == []


def test_run_trivy_unparseable_output_returns_none(libcvecheck: ModuleType, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(libcvecheck, "run", lambda cmd, **kw: trivy_result(returncode=1, stderr="pull failed"))
    assert libcvecheck.run_trivy("org/repo:1.0.0") is None


def test_run_trivy_nonzero_exit_with_parseable_output_returns_none(
    libcvecheck: ModuleType, monkeypatch: pytest.MonkeyPatch
):
    """A failed trivy/docker run can still print valid JSON; it must count
    as a scan error, never as a clean scan."""
    monkeypatch.setattr(libcvecheck, "run", lambda cmd, **kw: trivy_result(returncode=1, stdout="{}"))
    assert libcvecheck.run_trivy("org/repo:1.0.0") is None


def test_digest_ref_uses_the_pinned_digest(libcvecheck: ModuleType):
    assert libcvecheck._digest_ref("org/repo", DIGEST_A) == f"docker.io/org/repo@sha256:{DIGEST_A}"


def test_digest_ref_without_a_digest_is_none(libcvecheck: ModuleType):
    assert libcvecheck._digest_ref("org/repo", "") is None


# --- scan_cached (shared by check_cves and lib.checks.cve_diff) ---


def test_scan_cached_reports_a_hit_and_never_calls_run_trivy(
    libcvecheck: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
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


def test_scan_cached_reports_a_fresh_scan_and_writes_the_cache(
    libcvecheck: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
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


def test_scan_cached_stale_entry_is_not_used(libcvecheck: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
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


def test_scan_cached_none_digest_skips_the_cache_entirely(
    libcvecheck: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """digest=None (unresolved proposed tag) goes straight to run_trivy: no cache read or write."""
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


def test_scan_cached_failed_scan_returns_none_and_is_never_cached(
    libcvecheck: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
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


def test_scan_cached_default_label_is_this_image(
    libcvecheck: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    monkeypatch.setattr(libcvecheck, "run_trivy", lambda ref: [])
    libcvecheck.scan_cached(
        tmp_path,
        libcvecheck.ScanTarget("org/repo", DIGEST_A, "org/repo:1.0.0"),
        libcvecheck.CacheSession({}, {}),
        CVE_CACHE_TTL_DAYS,
    )
    out = capsys.readouterr().out
    assert "this image: scanning fresh" in out


# --- open_cache_session (shared by check_cves and cve_diff so the init can't drift) ---


def test_open_cache_session_new_cache_is_a_separate_copy(libcvecheck: ModuleType, tmp_path: Path):
    key = libcvecheck.cache_key("org/repo", DIGEST_A)
    entry = {"scanned_at": datetime.now(timezone.utc).isoformat(), "vulnerabilities": []}
    libcvecheck.save_cache(tmp_path, {key: entry})

    old_cache, new_cache = libcvecheck.open_cache_session(tmp_path)

    assert old_cache == {key: entry}
    assert new_cache == old_cache
    assert new_cache is not old_cache  # mutating one must never affect the other

    new_cache["org/other@sha256:" + "b" * 64] = {"vulnerabilities": []}
    assert "org/other@sha256:" + "b" * 64 not in old_cache


def test_open_cache_session_empty_when_no_cache_file_exists(libcvecheck: ModuleType, tmp_path: Path):
    old_cache, new_cache = libcvecheck.open_cache_session(tmp_path)
    assert old_cache == {}
    assert new_cache == {}
    assert new_cache is not old_cache


def test_check_cves_routes_through_open_cache_session(
    vp: ModuleType, libcvecheck: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
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


def test_classify_source_own(libcvecheck: ModuleType):
    assert libcvecheck.classify_source("podiumd/templates/frankgateway.yaml", {}) == "own"


def test_classify_source_partner(libcvecheck: ModuleType):
    vendor_map = {"openzaak": "Maykin"}
    assert libcvecheck.classify_source("podiumd/charts/openzaak/templates/deployment.yaml", vendor_map) == "Maykin"


def test_classify_source_other(libcvecheck: ModuleType):
    assert libcvecheck.classify_source("podiumd/charts/redis-operator/templates/deployment.yaml", {}) == "other"


def test_classify_by_key_own_when_not_a_dependency(libcvecheck: ModuleType):
    assert libcvecheck.classify_by_key("frankgateway", {"openzaak"}, {}) == "own"


def test_classify_by_key_partner_when_dependency_and_friendly(libcvecheck: ModuleType):
    assert libcvecheck.classify_by_key("openzaak", {"openzaak"}, {"openzaak": "Maykin"}) == "Maykin"


def test_classify_by_key_other_when_dependency_but_not_friendly(libcvecheck: ModuleType):
    assert libcvecheck.classify_by_key("redis-operator", {"redis-operator"}, {}) == "other"


def test_bucket_of(libcvecheck: ModuleType):
    assert libcvecheck.bucket_of("own") == "own"
    assert libcvecheck.bucket_of("other") == "other"
    assert libcvecheck.bucket_of("Maykin") == "partner"


def test_parse_image_ref(libcvecheck: ModuleType):
    assert libcvecheck.parse_image_ref(f"org/repo:1.0.0@sha256:{DIGEST_A}") == ("org/repo", "1.0.0", DIGEST_A)


def test_parse_image_ref_tagless_digest_reference(libcvecheck: ModuleType):
    """A digest ref without :tag must return version=None, not raise on tuple unpack."""
    assert libcvecheck.parse_image_ref(f"ghcr.io/foo/bar@sha256:{DIGEST_A}") == ("ghcr.io/foo/bar", None, DIGEST_A)


def test_parse_image_ref_registry_port_is_not_a_tag(libcvecheck: ModuleType):
    assert libcvecheck.parse_image_ref(f"registry.example.com:5000/foo/bar@sha256:{DIGEST_A}") == (
        "registry.example.com:5000/foo/bar",
        None,
        DIGEST_A,
    )


def test_top_level_key_for_line(libcvecheck: ModuleType):
    lines = ["frankgateway:", "  image:", "    tag: x", "openzaak:", "  image:", "    tag: y"]
    assert libcvecheck.top_level_key_for_line(lines, 3) == "frankgateway"
    assert libcvecheck.top_level_key_for_line(lines, 6) == "openzaak"


def test_render_image_labels_own_wins_over_other_sources(libcvecheck: ModuleType):
    """An image used by both an own template and a vendored chart classifies as "own"."""
    rendered = (
        f"---\n# Source: podiumd/templates/foo.yaml\napiVersion: v1\nkind: Pod\nmetadata:\n  name: a\n"
        f"spec:\n  containers:\n    - name: a\n      image: shared/img:1.0@sha256:{DIGEST_A}\n"
        f"---\n# Source: podiumd/charts/other/templates/bar.yaml\napiVersion: v1\nkind: Pod\nmetadata:\n  name: b\n"
        f"spec:\n  containers:\n    - name: b\n      image: shared/img:1.0@sha256:{DIGEST_A}\n"
    )
    labels = libcvecheck.render_image_labels(rendered, {})
    assert labels[("shared/img", "1.0", DIGEST_A)] == "own"


# --- per-package grouping/summarization ---


def test_severity_label_abbreviates_critical(libcvecheck: ModuleType):
    assert libcvecheck.severity_label("CRITICAL") == "CRIT"
    assert libcvecheck.severity_label("HIGH") == "HIGH"


def test_findings_by_package_groups_every_severity(libcvecheck: ModuleType):
    vulns = [
        vuln("CRITICAL", cve="CVE-1", pkg="chromium"),
        vuln("HIGH", cve="CVE-2", pkg="chromium"),
        vuln("HIGH", cve="CVE-3", pkg="openssl"),
        vuln("LOW", cve="CVE-4", pkg="chromium"),
    ]
    groups = libcvecheck.findings_by_package(vulns)
    assert {v["VulnerabilityID"] for v in groups["chromium"]} == {"CVE-1", "CVE-2", "CVE-4"}
    assert {v["VulnerabilityID"] for v in groups["openssl"]} == {"CVE-3"}


def test_print_package_line_lists_ids_below_threshold(libcvecheck: ModuleType, capsys: pytest.CaptureFixture[str]):
    vulns_for_pkg = [vuln("CRITICAL", cve="CVE-1"), vuln("HIGH", cve="CVE-2")]
    libcvecheck.print_package_line("libwebp", vulns_for_pkg, PACKAGE_CVE_LIST_THRESHOLD)
    out = capsys.readouterr().out
    assert "libwebp: CRIT CVE-1, HIGH CVE-2" in out


def test_print_package_line_summarizes_above_threshold(libcvecheck: ModuleType, capsys: pytest.CaptureFixture[str]):
    threshold = PACKAGE_CVE_LIST_THRESHOLD
    vulns_for_pkg = [vuln("CRITICAL", cve=f"CVE-{i}") for i in range(threshold + 1)]
    libcvecheck.print_package_line("chromium", vulns_for_pkg, threshold)
    out = capsys.readouterr().out
    assert f"chromium: {threshold + 1} CVE(s) ({threshold + 1} CRIT)" in out


def test_print_package_line_never_shows_fix_version(libcvecheck: ModuleType, capsys: pytest.CaptureFixture[str]):
    """FixedVersion is never shown: it's a base-image package detail this repo can't bump,
    and per-CVE values can differ wildly for one package (e.g. Debian bind9-dnsutils)."""
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


def test_check_cves_no_docker_passes_and_skips(vp: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    chart_dir = make_chart_dir(tmp_path)
    monkeypatch.setattr(vp.shutil, "which", lambda name: None)
    ok, detail = vp.check_cves(chart_dir, [])
    assert ok is True
    assert "not installed" in detail


def test_check_cves_render_failure_fails(
    vp: ModuleType, libcvecheck: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    chart_dir = make_chart_dir(tmp_path)
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr(libcvecheck, "render_chart", fake_render_chart("", returncode=1))
    ok, detail = vp.check_cves(chart_dir, [])
    assert ok is False
    assert "failed to render" in detail


# --- check_cves: full own/partner/other integration ---


def test_check_cves_splits_own_partner_other_and_never_fails(
    vp: ModuleType,
    libcvecheck: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    chart_dir = make_chart_dir(tmp_path)
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/docker")

    trivy_by_image = {
        f"ghcr.io/wearefrank/frank-gateway@sha256:{DIGEST_A}": trivy_result(
            stdout=json.dumps(
                {"Results": [{"Vulnerabilities": [vuln("CRITICAL", cve="CVE-OWN-1"), vuln("LOW", cve="CVE-OWN-2")]}]}
            )
        ),
        f"docker.io/maykinmedia/objects-api@sha256:{DIGEST_B}": trivy_result(
            stdout=json.dumps({"Results": [{"Vulnerabilities": [vuln("HIGH", cve="CVE-PARTNER-1")]}]})
        ),
        f"docker.io/alpine/k8s@sha256:{DIGEST_C}": trivy_result(
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
    assert "1 CRIT, 1 MEDIUM CVE(s)" in out  # other-vendor: same treatment as own/partner
    assert "CVE-OTHER-1" not in out  # totals only by default, no individual CVE IDs

    # a per-image progress line per uncached scan, so a slow trivy pull doesn't look hung
    scan_lines = [line for line in out.splitlines() if "scanning fresh" in line and "docker pull + trivy" in line]
    assert len(scan_lines) == 3
    assert any(line.startswith("  [1/3] this image: scanning fresh ") for line in scan_lines)
    assert any(line.startswith("  [3/3] this image: scanning fresh ") for line in scan_lines)


def test_check_cves_marks_upgradable_from_image_upgrade_cache(
    vp: ModuleType,
    libcvecheck: ModuleType,
    libimageupgradecache: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """An image with a fresh upgrade-cache entry showing a newer tag gets " upgradable to X";
    one without a cache entry gets no marker."""
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
        f"ghcr.io/wearefrank/frank-gateway@sha256:{DIGEST_A}": trivy_result(
            stdout=json.dumps({"Results": [{"Vulnerabilities": [vuln("CRITICAL", cve="CVE-OWN-1")]}]})
        ),
        f"docker.io/maykinmedia/objects-api@sha256:{DIGEST_B}": trivy_result(
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
    vp: ModuleType,
    libcvecheck: ModuleType,
    libimageupgradecache: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """A stale upgrade-cache entry is not evidence of an upgrade: cve_check never refreshes it."""
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
        f"ghcr.io/wearefrank/frank-gateway@sha256:{DIGEST_A}": trivy_result(
            stdout=json.dumps({"Results": [{"Vulnerabilities": [vuln("CRITICAL", cve="CVE-OWN-1")]}]})
        ),
    }
    monkeypatch.setattr(libcvecheck, "run", sequenced_run(trivy_by_image=trivy_by_image))

    ok, _detail = vp.check_cves(chart_dir, [])
    assert ok is True
    out = capsys.readouterr().out
    assert "upgradable" not in out


def test_check_cves_detail_itemizes_every_bucket(
    vp: ModuleType,
    libcvecheck: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """detail=True itemizes every finding per package for all three buckets, other-vendor included."""
    chart_dir = make_chart_dir(tmp_path)
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/docker")

    trivy_by_image = {
        f"ghcr.io/wearefrank/frank-gateway@sha256:{DIGEST_A}": trivy_result(
            stdout=json.dumps(
                {"Results": [{"Vulnerabilities": [vuln("CRITICAL", cve="CVE-OWN-1"), vuln("LOW", cve="CVE-OWN-2")]}]}
            )
        ),
        f"docker.io/maykinmedia/objects-api@sha256:{DIGEST_B}": trivy_result(
            stdout=json.dumps({"Results": [{"Vulnerabilities": [vuln("HIGH", cve="CVE-PARTNER-1", pkg="curl")]}]})
        ),
        f"docker.io/alpine/k8s@sha256:{DIGEST_C}": trivy_result(
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
    assert "openssl: CRIT CVE-OWN-1, LOW CVE-OWN-2" in out  # own: every severity itemized
    assert "curl: HIGH CVE-PARTNER-1" in out  # partner: itemized too
    assert "busybox: CRIT CVE-OTHER-1" in out  # other-vendor: itemized too
    assert "openssl: MEDIUM CVE-OTHER-2" in out  # MEDIUM itemized as well with --detail
    assert "1 CRIT, 1 MEDIUM CVE(s)" in out  # the totals line stays


def test_print_bucket_report_image_line_then_totals_then_packages(
    libcvecheck: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """Itemized layout: name+vendor(+upgradable) line, severity totals, then every finding per package."""
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
        libcvecheck.ReportSettings("full", PACKAGE_CVE_LIST_THRESHOLD),
    )

    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    header_idx = next(i for i, line in enumerate(lines) if line.startswith("docker.io/pravega/zookeeper:0.2.15"))
    assert lines[header_idx:] == [
        "docker.io/pravega/zookeeper:0.2.15 upgradable to 0.2.16",
        "  1 HIGH, 1 MEDIUM, 1 LOW CVE(s)",
        "  bind9-dnsutils: HIGH CVE-1",
        "  openssl: MEDIUM CVE-2, LOW CVE-3",
    ]


def test_print_bucket_report_totals_mode_never_itemizes_even_high_severity(
    libcvecheck: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """detail_level="totals" gives one severity-totals line, no package breakdown or CVE IDs."""
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
        libcvecheck.ReportSettings("totals", PACKAGE_CVE_LIST_THRESHOLD),
    )

    out = capsys.readouterr().out
    assert "docker.io/maykinmedia/objects-api:1.0.0 [Maykin]\n" in out
    assert "upgradable" not in out
    assert "1 CRIT, 1 HIGH, 1 MEDIUM CVE(s)" in out
    assert "CVE-1" not in out and "CVE-2" not in out and "CVE-3" not in out
    assert "openssl" not in out


def test_check_cves_no_findings_passes(
    vp: ModuleType,
    libcvecheck: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    chart_dir = make_chart_dir(tmp_path)
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr(libcvecheck, "run", sequenced_run())

    ok, detail = vp.check_cves(chart_dir, [])
    assert ok is True
    assert "0 own (0 img)" in detail
    out = capsys.readouterr().out
    assert "OK: no known CVEs" in out


def test_check_cves_scan_error_reported_but_still_passes(
    vp: ModuleType,
    libcvecheck: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    chart_dir = make_chart_dir(tmp_path)
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/docker")
    trivy_by_image = {
        f"ghcr.io/wearefrank/frank-gateway@sha256:{DIGEST_A}": trivy_result(returncode=1, stdout="not json")
    }
    monkeypatch.setattr(libcvecheck, "run", sequenced_run(trivy_by_image=trivy_by_image))

    ok, detail = vp.check_cves(chart_dir, [])
    assert ok is True
    assert "1 scan error(s)" in detail
    out = capsys.readouterr().out
    assert "SCAN-ERR" in out
    assert "could not be scanned:\n  ghcr.io/wearefrank/frank-gateway:104" in out


def test_check_cves_heuristic_fallback_for_disabled_component(
    vp: ModuleType,
    libcvecheck: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """A pin not in the render (e.g. disabled in CI values) falls back to the values-key
    heuristic: not a Chart.yaml dependency -> own."""
    apiproxy_digest = "d" * 64
    values = VALUES_YAML + (
        f'apiproxy:\n  image:\n    repository: org/apiproxy\n    tag: "1.0.0@sha256:{apiproxy_digest}"\n'
    )
    chart_dir = make_chart_dir(tmp_path, values=values)
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/docker")

    trivy_by_image = {
        f"docker.io/org/apiproxy@sha256:{apiproxy_digest}": trivy_result(
            stdout=json.dumps({"Results": [{"Vulnerabilities": [vuln("HIGH", cve="CVE-APIPROXY")]}]})
        ),
    }
    monkeypatch.setattr(libcvecheck, "run", sequenced_run(trivy_by_image=trivy_by_image))

    ok, detail = vp.check_cves(chart_dir, [])
    assert ok is True
    # only apiproxy has findings; the point is it lands in "own" via the heuristic fallback
    assert "1 own (1 img)" in detail
    out = capsys.readouterr().out
    assert "docker.io/org/apiproxy:1.0.0" in out
    assert "1 HIGH CVE(s)" in out  # own: per-image totals by default, no CVE ID itemized
    assert "CVE-APIPROXY" not in out


# --- caching ---


def test_check_cves_cache_miss_scans_and_persists(
    vp: ModuleType, libcvecheck: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    chart_dir = make_chart_dir(tmp_path)
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr(libcvecheck, "run", sequenced_run())

    ok, _detail = vp.check_cves(chart_dir, [])
    assert ok is True
    saved = libcvecheck.load_cache(chart_dir)
    assert libcvecheck.cache_key("ghcr.io/wearefrank/frank-gateway", DIGEST_A) in saved


def test_check_cves_cache_hit_skips_scanning(
    vp: ModuleType,
    libcvecheck: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
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


def test_check_cves_expired_cache_entry_rescans(
    vp: ModuleType,
    libcvecheck: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
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


def test_check_cves_preserves_entries_for_unpinned_images(
    vp: ModuleType, libcvecheck: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Regression: new_cache must start as a copy of old_cache, not {}.

    check_cves runs right before check_cve_diff; an empty start made its save wipe
    cve-diff's proposed-side entries (images never pinned in values.yaml). Untouched
    entries now age out on their own TTL."""
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


def test_check_cves_still_updates_its_own_currently_pinned_targets(
    vp: ModuleType,
    libcvecheck: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """Copying old_cache must not stop check_cves adding/refreshing its own targets."""
    chart_dir = make_chart_dir(tmp_path)
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr(libcvecheck, "run", sequenced_run())

    ok, _detail = vp.check_cves(chart_dir, [])
    assert ok is True
    saved = libcvecheck.load_cache(chart_dir)
    assert libcvecheck.cache_key("ghcr.io/wearefrank/frank-gateway", DIGEST_A) in saved
