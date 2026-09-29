"""check_cve_diff: per-severity CVE difference between current and proposed images.

Candidates come from check_image_upgrades (newer tag) and check_image_digests
(slid digest), bucketed own/partner-vendor/other-vendor like check_cves. No
real docker/trivy/registry calls: load_upgrade_cache/find_sliding_pins/
registry_tag_exists are mocked on lib.checks.cve_diff, but run_trivy and
cache_key on lib.checks.cve (`libcvecheck`), because scans go through
lib.checks.cve.scan_cached.

classify_candidates needs a Chart.yaml and calls render_chart: make_chart_dir
writes a dependency-less Chart.yaml and an autouse fixture makes the render
fail, so candidates default to "own". Bucket-split tests override both."""

import urllib.error

from datetime import datetime
from datetime import timedelta
from datetime import timezone
from pathlib import Path
from types import ModuleType
from types import SimpleNamespace

import pytest

DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64

MINIMAL_CHART_YAML = """\
apiVersion: v2
name: podiumd
version: 0.0.1
"""


def write_chart_yaml(chart_dir, text=MINIMAL_CHART_YAML):
    (chart_dir / "Chart.yaml").write_text(text, encoding="utf-8")


def write_values_yaml(chart_dir, text):
    """Write values.yaml plus a dependency-less Chart.yaml unless one exists.

    classify_candidates reads Chart.yaml unconditionally; with no dependencies
    every candidate falls back to "own"."""
    if not (chart_dir / "Chart.yaml").exists():
        write_chart_yaml(chart_dir)
    (chart_dir / "values.yaml").write_text(text, encoding="utf-8")


def make_chart_dir(tmp_path: Path, values, chart_yaml=MINIMAL_CHART_YAML):
    write_chart_yaml(tmp_path, chart_yaml)
    write_values_yaml(tmp_path, values)
    return tmp_path


def vuln(severity, cve, pkg):
    return {"VulnerabilityID": cve, "PkgName": pkg, "Severity": severity}


def fresh_upgrade_entry(newest):
    return {"checked_at": datetime.now(timezone.utc).isoformat(), "newest": newest}


def stale_upgrade_entry(newest):
    return {"checked_at": (datetime.now(timezone.utc) - timedelta(days=30)).isoformat(), "newest": newest}


def make_run_trivy(vulns_by_ref, calls=None):
    def _run_trivy(ref):
        if calls is not None:
            calls.append(ref)
        return vulns_by_ref.get(ref, [])

    return _run_trivy


def fake_render_chart(rendered="", returncode=1):
    """Default to a failing render so classify_candidates falls back to classify_by_key."""

    def render_chart(chart_dir, extra_args):
        return SimpleNamespace(returncode=returncode, stdout=rendered, stderr="")

    return render_chart


@pytest.fixture(autouse=True)
def _default_render(libcvediffcheck: ModuleType, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(libcvediffcheck, "render_chart", fake_render_chart())


# --- diff_vulns ---


def test_diff_vulns_exact_set_difference_per_severity(libcvediffcheck: ModuleType):
    current = [vuln("CRITICAL", "CVE-1", "openssl"), vuln("HIGH", "CVE-2", "libxml2")]
    proposed = [vuln("HIGH", "CVE-2", "libxml2"), vuln("MEDIUM", "CVE-3", "curl")]

    closed, introduced = libcvediffcheck.diff_vulns(current, proposed)

    assert closed == [vuln("CRITICAL", "CVE-1", "openssl")]
    assert introduced == [vuln("MEDIUM", "CVE-3", "curl")]


def test_diff_vulns_never_collapses_into_a_naive_net_count(libcvediffcheck: ModuleType):
    """5 closed + 3 introduced stay two lists, never a misleading "net -2"."""
    current = [vuln("HIGH", f"CVE-{i}", "pkg") for i in range(5)]
    proposed = [vuln("HIGH", f"CVE-new-{i}", "pkg") for i in range(3)]

    closed, introduced = libcvediffcheck.diff_vulns(current, proposed)

    assert len(closed) == 5
    assert len(introduced) == 3


# --- check_cve_diff: "upgrade" candidates ---


def test_upgrade_candidate_reports_correct_closed_and_introduced(
    libcvediffcheck: ModuleType,
    libcvecheck: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    write_values_yaml(
        tmp_path,
        f"""\
zac:
  image:
    repository: ghcr.io/infonl/zac
    tag: "1.0.0@sha256:{DIGEST_A}"
""",
    )
    monkeypatch.setattr(
        libcvediffcheck,
        "load_upgrade_cache",
        lambda chart_dir: {"ghcr.io/infonl/zac:1.0.0": fresh_upgrade_entry("1.1.0")},
    )
    monkeypatch.setattr(libcvediffcheck, "find_sliding_pins", lambda chart_dir: [])
    monkeypatch.setattr(libcvediffcheck, "registry_tag_exists", lambda host, repo, tag: (False, None))

    vulns_by_ref = {
        "ghcr.io/infonl/zac:1.0.0": [vuln("CRITICAL", "CVE-1", "openssl"), vuln("HIGH", "CVE-2", "libxml2")],
        "ghcr.io/infonl/zac:1.1.0": [vuln("HIGH", "CVE-2", "libxml2"), vuln("MEDIUM", "CVE-3", "curl")],
    }
    monkeypatch.setattr(libcvecheck, "run_trivy", make_run_trivy(vulns_by_ref))

    ok, detail = libcvediffcheck.check_cve_diff(tmp_path, [])

    assert ok is True
    assert "1 own (1 closed, 1 introduced)" in detail
    out = capsys.readouterr().out
    assert "ghcr.io/infonl/zac: 1.0.0 -> 1.1.0  [upgrade]" in out
    assert "closed: 1 CRIT" in out
    assert "introduced: 1 MEDIUM" in out


def test_upgrade_candidate_current_ref_is_the_plain_pinned_tag(
    libcvediffcheck: ModuleType, libcvecheck: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """An "upgrade" candidate's current side is the bare pinned tag: its digest has not drifted."""
    write_values_yaml(
        tmp_path,
        f"""\
zac:
  image:
    repository: ghcr.io/infonl/zac
    tag: "1.0.0@sha256:{DIGEST_A}"
""",
    )
    monkeypatch.setattr(
        libcvediffcheck,
        "load_upgrade_cache",
        lambda chart_dir: {"ghcr.io/infonl/zac:1.0.0": fresh_upgrade_entry("1.1.0")},
    )
    monkeypatch.setattr(libcvediffcheck, "find_sliding_pins", lambda chart_dir: [])
    monkeypatch.setattr(libcvediffcheck, "registry_tag_exists", lambda host, repo, tag: (False, None))

    calls = []
    monkeypatch.setattr(libcvecheck, "run_trivy", make_run_trivy({}, calls))

    libcvediffcheck.check_cve_diff(tmp_path, [])

    assert "ghcr.io/infonl/zac:1.0.0" in calls
    assert "ghcr.io/infonl/zac:1.1.0" in calls


def test_stale_upgrade_cache_entry_is_not_a_candidate(
    libcvediffcheck: ModuleType, libcvecheck: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    write_values_yaml(
        tmp_path,
        f"""\
zac:
  image:
    repository: ghcr.io/infonl/zac
    tag: "1.0.0@sha256:{DIGEST_A}"
""",
    )
    monkeypatch.setattr(
        libcvediffcheck,
        "load_upgrade_cache",
        lambda chart_dir: {"ghcr.io/infonl/zac:1.0.0": stale_upgrade_entry("1.1.0")},
    )
    monkeypatch.setattr(libcvediffcheck, "find_sliding_pins", lambda chart_dir: [])

    calls = []
    monkeypatch.setattr(libcvecheck, "run_trivy", make_run_trivy({}, calls))

    ok, detail = libcvediffcheck.check_cve_diff(tmp_path, [])

    assert ok is True
    assert detail == "0 candidate(s)"
    assert calls == []


# --- check_cve_diff: "sliding digest" candidates ---


def test_sliding_candidate_uses_pinned_digest_not_bare_tag_for_current_side(
    libcvediffcheck: ModuleType,
    libcvecheck: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """The tag now resolves to the new upstream digest, so current_ref must be
    "repo@sha256:<pinned_digest>", never "repo:version"."""
    write_values_yaml(
        tmp_path,
        f"""\
openzaak:
  redis:
    image:
      repository: redis
      tag: "8.0@sha256:{DIGEST_A}"
""",
    )
    monkeypatch.setattr(libcvediffcheck, "load_upgrade_cache", lambda chart_dir: {})
    monkeypatch.setattr(
        libcvediffcheck, "find_sliding_pins", lambda chart_dir: [("redis", "8.0", DIGEST_A, f"sha256:{DIGEST_B}")]
    )

    calls = []
    vulns_by_ref = {
        f"redis@sha256:{DIGEST_A}": [vuln("CRITICAL", "CVE-1", "openssl")],
        f"redis@sha256:{DIGEST_B}": [],
    }
    monkeypatch.setattr(libcvecheck, "run_trivy", make_run_trivy(vulns_by_ref, calls))

    ok, _detail = libcvediffcheck.check_cve_diff(tmp_path, [])

    assert ok is True
    assert f"redis@sha256:{DIGEST_A}" in calls
    assert f"redis@sha256:{DIGEST_B}" in calls
    assert "redis:8.0" not in calls
    out = capsys.readouterr().out
    assert "[sliding digest]" in out
    assert "closed: 1 CRIT" in out


# --- check_cve_diff: caching the PROPOSED side ---


def test_sliding_candidate_proposed_side_caches_across_runs(
    libcvediffcheck: ModuleType, libcvecheck: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A sliding candidate's proposed digest is already known, so a second run reuses the cached scan."""
    write_values_yaml(
        tmp_path,
        f"""\
openzaak:
  redis:
    image:
      repository: redis
      tag: "8.0@sha256:{DIGEST_A}"
""",
    )
    monkeypatch.setattr(libcvediffcheck, "load_upgrade_cache", lambda chart_dir: {})
    monkeypatch.setattr(
        libcvediffcheck, "find_sliding_pins", lambda chart_dir: [("redis", "8.0", DIGEST_A, f"sha256:{DIGEST_B}")]
    )

    calls = []
    vulns_by_ref = {
        f"redis@sha256:{DIGEST_A}": [vuln("CRITICAL", "CVE-1", "openssl")],
        f"redis@sha256:{DIGEST_B}": [vuln("HIGH", "CVE-2", "libxml2")],
    }
    monkeypatch.setattr(libcvecheck, "run_trivy", make_run_trivy(vulns_by_ref, calls))

    libcvediffcheck.check_cve_diff(tmp_path, [])
    assert calls.count(f"redis@sha256:{DIGEST_B}") == 1  # first run: a real scan

    calls.clear()
    libcvediffcheck.check_cve_diff(tmp_path, [])
    assert f"redis@sha256:{DIGEST_B}" not in calls  # second run: cache hit, no new scan


def test_upgrade_candidate_proposed_side_resolves_digest_then_caches_across_runs(
    libcvediffcheck: ModuleType, libcvecheck: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """An "upgrade" proposed tag is resolved by one registry_tag_exists call (host, repo_path,
    newest-tag), never a docker pull; a second run then reuses the cached scan."""
    write_values_yaml(
        tmp_path,
        f"""\
zac:
  image:
    repository: ghcr.io/infonl/zac
    tag: "1.0.0@sha256:{DIGEST_A}"
""",
    )
    monkeypatch.setattr(
        libcvediffcheck,
        "load_upgrade_cache",
        lambda chart_dir: {"ghcr.io/infonl/zac:1.0.0": fresh_upgrade_entry("1.1.0")},
    )
    monkeypatch.setattr(libcvediffcheck, "find_sliding_pins", lambda chart_dir: [])

    resolve_calls = []

    def fake_registry_tag_exists(host, repo, tag):
        resolve_calls.append((host, repo, tag))
        return True, f"sha256:{DIGEST_B}"

    monkeypatch.setattr(libcvediffcheck, "registry_tag_exists", fake_registry_tag_exists)

    trivy_calls = []
    vulns_by_ref = {
        "ghcr.io/infonl/zac:1.0.0": [],
        "ghcr.io/infonl/zac:1.1.0": [vuln("CRITICAL", "CVE-1", "openssl")],
    }
    monkeypatch.setattr(libcvecheck, "run_trivy", make_run_trivy(vulns_by_ref, trivy_calls))

    libcvediffcheck.check_cve_diff(tmp_path, [])
    assert resolve_calls == [("ghcr.io", "infonl/zac", "1.1.0")]
    assert trivy_calls.count("ghcr.io/infonl/zac:1.1.0") == 1  # first run: a real scan

    trivy_calls.clear()
    libcvediffcheck.check_cve_diff(tmp_path, [])
    assert "ghcr.io/infonl/zac:1.1.0" not in trivy_calls  # second run: cache hit, no new scan


def test_upgrade_candidate_resolve_failure_falls_back_to_uncached_scan(
    libcvediffcheck: ModuleType,
    libcvecheck: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """A network error resolving the proposed digest falls back to an uncached scan, not an error."""
    write_values_yaml(
        tmp_path,
        f"""\
zac:
  image:
    repository: ghcr.io/infonl/zac
    tag: "1.0.0@sha256:{DIGEST_A}"
""",
    )
    monkeypatch.setattr(
        libcvediffcheck,
        "load_upgrade_cache",
        lambda chart_dir: {"ghcr.io/infonl/zac:1.0.0": fresh_upgrade_entry("1.1.0")},
    )
    monkeypatch.setattr(libcvediffcheck, "find_sliding_pins", lambda chart_dir: [])

    def failing_resolve(host, repo, tag):
        msg = "network down"
        raise urllib.error.URLError(msg)

    monkeypatch.setattr(libcvediffcheck, "registry_tag_exists", failing_resolve)

    vulns_by_ref = {
        "ghcr.io/infonl/zac:1.0.0": [],
        "ghcr.io/infonl/zac:1.1.0": [vuln("CRITICAL", "CVE-1", "openssl")],
    }
    monkeypatch.setattr(libcvecheck, "run_trivy", make_run_trivy(vulns_by_ref))

    ok, detail = libcvediffcheck.check_cve_diff(tmp_path, [])

    assert ok is True
    assert "0 scan error(s)" in detail
    out = capsys.readouterr().out
    assert "introduced: 1 CRIT" in out


def test_cache_hit_and_fresh_scan_are_both_reported_per_side(
    libcvediffcheck: ModuleType,
    libcvecheck: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """Cache hit vs fresh scan is reported per side, not as one blanket caveat."""
    write_values_yaml(
        tmp_path,
        f"""\
zac:
  image:
    repository: ghcr.io/infonl/zac
    tag: "1.0.0@sha256:{DIGEST_A}"
""",
    )
    monkeypatch.setattr(
        libcvediffcheck,
        "load_upgrade_cache",
        lambda chart_dir: {"ghcr.io/infonl/zac:1.0.0": fresh_upgrade_entry("1.1.0")},
    )
    monkeypatch.setattr(libcvediffcheck, "find_sliding_pins", lambda chart_dir: [])
    monkeypatch.setattr(libcvediffcheck, "registry_tag_exists", lambda host, repo, tag: (False, None))

    # pre-populate the shared cve-scan cache for the CURRENT side only
    libcvediffcheck.save_cache(
        tmp_path,
        {
            libcvecheck.cache_key("ghcr.io/infonl/zac", DIGEST_A): {
                "scanned_at": datetime.now(timezone.utc).isoformat(),
                "vulnerabilities": [],
            },
        },
    )

    trivy_calls = []
    vulns_by_ref = {"ghcr.io/infonl/zac:1.1.0": [vuln("CRITICAL", "CVE-1", "openssl")]}
    monkeypatch.setattr(libcvecheck, "run_trivy", make_run_trivy(vulns_by_ref, trivy_calls))

    libcvediffcheck.check_cve_diff(tmp_path, [])

    out = capsys.readouterr().out
    assert "current: served from cache" in out
    assert "proposed: scanning fresh (docker pull + trivy)" in out
    assert "ghcr.io/infonl/zac:1.0.0" not in trivy_calls  # current side never actually scanned


# --- check_cve_diff: no flagged candidate at all ---


def test_no_flagged_upgrade_or_slide_never_scans_anything(
    libcvediffcheck: ModuleType,
    libcvecheck: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    write_values_yaml(
        tmp_path,
        f"""\
zac:
  image:
    repository: ghcr.io/infonl/zac
    tag: "1.0.0@sha256:{DIGEST_A}"
""",
    )
    monkeypatch.setattr(
        libcvediffcheck,
        "load_upgrade_cache",
        lambda chart_dir: {"ghcr.io/infonl/zac:1.0.0": fresh_upgrade_entry("1.0.0")},
    )
    monkeypatch.setattr(libcvediffcheck, "find_sliding_pins", lambda chart_dir: [])

    calls = []
    monkeypatch.setattr(libcvecheck, "run_trivy", make_run_trivy({}, calls))

    ok, detail = libcvediffcheck.check_cve_diff(tmp_path, [])

    assert ok is True
    assert detail == "0 candidate(s)"
    assert calls == []
    out = capsys.readouterr().out
    assert "OK: no upgrade-available or sliding-digest candidate to diff" in out


# --- detail mode (--detail-cve-diff) ---


def test_default_report_is_terse_counts_only(
    libcvediffcheck: ModuleType,
    libcvecheck: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    write_values_yaml(
        tmp_path,
        f"""\
zac:
  image:
    repository: ghcr.io/infonl/zac
    tag: "1.0.0@sha256:{DIGEST_A}"
""",
    )
    monkeypatch.setattr(
        libcvediffcheck,
        "load_upgrade_cache",
        lambda chart_dir: {"ghcr.io/infonl/zac:1.0.0": fresh_upgrade_entry("1.1.0")},
    )
    monkeypatch.setattr(libcvediffcheck, "find_sliding_pins", lambda chart_dir: [])
    monkeypatch.setattr(libcvediffcheck, "registry_tag_exists", lambda host, repo, tag: (False, None))

    vulns_by_ref = {
        "ghcr.io/infonl/zac:1.0.0": [],
        "ghcr.io/infonl/zac:1.1.0": [vuln("CRITICAL", "CVE-1", "openssl")],
    }
    monkeypatch.setattr(libcvecheck, "run_trivy", make_run_trivy(vulns_by_ref))

    libcvediffcheck.check_cve_diff(tmp_path, [])

    out = capsys.readouterr().out
    assert "introduced: 1 CRIT" in out
    assert "CVE-1" not in out
    assert "openssl" not in out


def test_detail_flag_itemizes_high_severity_vulnerability_id_and_package(
    libcvediffcheck: ModuleType,
    libcvecheck: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    write_values_yaml(
        tmp_path,
        f"""\
zac:
  image:
    repository: ghcr.io/infonl/zac
    tag: "1.0.0@sha256:{DIGEST_A}"
""",
    )
    monkeypatch.setattr(
        libcvediffcheck,
        "load_upgrade_cache",
        lambda chart_dir: {"ghcr.io/infonl/zac:1.0.0": fresh_upgrade_entry("1.1.0")},
    )
    monkeypatch.setattr(libcvediffcheck, "find_sliding_pins", lambda chart_dir: [])
    monkeypatch.setattr(libcvediffcheck, "registry_tag_exists", lambda host, repo, tag: (False, None))

    vulns_by_ref = {
        "ghcr.io/infonl/zac:1.0.0": [],
        "ghcr.io/infonl/zac:1.1.0": [vuln("CRITICAL", "CVE-1", "openssl")],
    }
    monkeypatch.setattr(libcvecheck, "run_trivy", make_run_trivy(vulns_by_ref))

    libcvediffcheck.check_cve_diff(tmp_path, [], detail=True)

    out = capsys.readouterr().out
    assert "introduced: 1 CRIT" in out
    assert "openssl" in out
    assert "CVE-1" in out


def test_detail_flag_never_itemizes_medium_low_unknown(
    libcvediffcheck: ModuleType,
    libcvecheck: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """Like check_cves' --detail-cve-check, only CRITICAL/HIGH are itemized."""
    write_values_yaml(
        tmp_path,
        f"""\
zac:
  image:
    repository: ghcr.io/infonl/zac
    tag: "1.0.0@sha256:{DIGEST_A}"
""",
    )
    monkeypatch.setattr(
        libcvediffcheck,
        "load_upgrade_cache",
        lambda chart_dir: {"ghcr.io/infonl/zac:1.0.0": fresh_upgrade_entry("1.1.0")},
    )
    monkeypatch.setattr(libcvediffcheck, "find_sliding_pins", lambda chart_dir: [])
    monkeypatch.setattr(libcvediffcheck, "registry_tag_exists", lambda host, repo, tag: (False, None))

    vulns_by_ref = {
        "ghcr.io/infonl/zac:1.0.0": [],
        "ghcr.io/infonl/zac:1.1.0": [vuln("MEDIUM", "CVE-9", "zlib")],
    }
    monkeypatch.setattr(libcvecheck, "run_trivy", make_run_trivy(vulns_by_ref))

    libcvediffcheck.check_cve_diff(tmp_path, [], detail=True)

    out = capsys.readouterr().out
    assert "introduced: 1 MEDIUM" in out
    assert "zlib" not in out
    assert "CVE-9" not in out


# --- open_cache_session (shared with check_cves, see lib.checks.cve) ---


def test_check_cve_diff_routes_through_open_cache_session(
    libcvediffcheck: ModuleType, libcvecheck: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    write_values_yaml(
        tmp_path,
        f"""\
zac:
  image:
    repository: ghcr.io/infonl/zac
    tag: "1.0.0@sha256:{DIGEST_A}"
""",
    )
    monkeypatch.setattr(
        libcvediffcheck,
        "load_upgrade_cache",
        lambda chart_dir: {"ghcr.io/infonl/zac:1.0.0": fresh_upgrade_entry("1.1.0")},
    )
    monkeypatch.setattr(libcvediffcheck, "find_sliding_pins", lambda chart_dir: [])
    monkeypatch.setattr(libcvediffcheck, "registry_tag_exists", lambda host, repo, tag: (False, None))
    monkeypatch.setattr(libcvecheck, "run_trivy", make_run_trivy({}))

    calls = []
    real_open_cache_session = libcvediffcheck.open_cache_session

    def spy(chart_dir_arg):
        calls.append(chart_dir_arg)
        return real_open_cache_session(chart_dir_arg)

    monkeypatch.setattr(libcvediffcheck, "open_cache_session", spy)
    libcvediffcheck.check_cve_diff(tmp_path, [])
    assert calls == [tmp_path]


# --- gather_candidates ---


def test_gather_candidates_combines_both_sources(
    libcvediffcheck: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    write_values_yaml(
        tmp_path,
        f"""\
zac:
  image:
    repository: ghcr.io/infonl/zac
    tag: "1.0.0@sha256:{DIGEST_A}"
redis-thing:
  image:
    repository: redis
    tag: "8.0@sha256:{DIGEST_A}"
""",
    )
    monkeypatch.setattr(
        libcvediffcheck,
        "load_upgrade_cache",
        lambda chart_dir: {"ghcr.io/infonl/zac:1.0.0": fresh_upgrade_entry("1.1.0")},
    )
    monkeypatch.setattr(
        libcvediffcheck, "find_sliding_pins", lambda chart_dir: [("redis", "8.0", DIGEST_A, f"sha256:{DIGEST_B}")]
    )

    candidates = libcvediffcheck.gather_candidates(tmp_path)

    kinds = sorted(c["kind"] for c in candidates)
    assert kinds == ["sliding digest", "upgrade"]

    by_kind = {c["kind"]: c for c in candidates}
    # sliding: proposed digest already resolved (bare hex, no "sha256:" prefix).
    assert by_kind["sliding digest"]["proposed_digest"] == DIGEST_B
    # upgrade: proposed side is a bare tag, resolved only when _scan_proposed needs it.
    assert by_kind["upgrade"]["proposed_digest"] is None


def test_gather_candidates_attaches_the_values_yaml_line_for_both_kinds(
    libcvediffcheck: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Both kinds carry the values.yaml line classify_by_key needs.

    find_sliding_pins returns no line, so sliding candidates look it up in
    targets by (repository, version)."""
    write_values_yaml(
        tmp_path,
        f"""\
zac:
  image:
    repository: ghcr.io/infonl/zac
    tag: "1.0.0@sha256:{DIGEST_A}"
redis-thing:
  image:
    repository: redis
    tag: "8.0@sha256:{DIGEST_A}"
""",
    )
    monkeypatch.setattr(
        libcvediffcheck,
        "load_upgrade_cache",
        lambda chart_dir: {"ghcr.io/infonl/zac:1.0.0": fresh_upgrade_entry("1.1.0")},
    )
    monkeypatch.setattr(
        libcvediffcheck, "find_sliding_pins", lambda chart_dir: [("redis", "8.0", DIGEST_A, f"sha256:{DIGEST_B}")]
    )

    candidates = libcvediffcheck.gather_candidates(tmp_path)
    by_kind = {c["kind"]: c for c in candidates}

    assert isinstance(by_kind["upgrade"]["line"], int)
    assert isinstance(by_kind["sliding digest"]["line"], int)


def test_classify_candidates_falls_back_to_classify_by_key_when_render_raises(
    libcvediffcheck: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """If render_chart raises (e.g. helm missing), classify_candidates falls back to classify_by_key."""
    write_values_yaml(
        tmp_path, f'zac:\n  image:\n    repository: ghcr.io/infonl/zac\n    tag: "1.0.0@sha256:{DIGEST_A}"\n'
    )

    def missing_helm(chart_dir: Path, extra_args: list[str]):
        msg = "helm"
        raise FileNotFoundError(msg)

    monkeypatch.setattr(libcvediffcheck, "render_chart", missing_helm)
    candidate = {
        "kind": "upgrade",
        "repository": "ghcr.io/infonl/zac",
        "version": "1.0.0",
        "current_ref": "ghcr.io/infonl/zac:1.0.0",
        "current_digest": DIGEST_A,
        "proposed_label": "1.1.0",
        "proposed_ref": "ghcr.io/infonl/zac:1.1.0",
        "proposed_digest": None,
        "line": 1,
    }
    values_lines = (tmp_path / "values.yaml").read_text(encoding="utf-8").splitlines()

    classified = libcvediffcheck.classify_candidates(tmp_path, [], [candidate], values_lines)

    assert [c["bucket"] for c in classified] == ["own"]


# --- check_cve_diff: own/partner/other bucket split ---
#
# Same fixture shape as test_cve_check.py. All candidates are "upgrade" kind
# (via load_upgrade_cache), attributed through the render's "# Source:" lines.

BUCKET_CHART_YAML = """\
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

BUCKET_VALUES_YAML = (
    "zac:\n"
    "  image:\n"
    "    repository: ghcr.io/infonl/zac\n"
    f'    tag: "1.0.0@sha256:{DIGEST_A}"\n'
    "openzaak:\n"
    "  image:\n"
    "    repository: maykinmedia/objects-api\n"
    f'    tag: "1.0.0@sha256:{DIGEST_B}"\n'
    "redis-operator:\n"
    "  image:\n"
    "    repository: docker.io/alpine/k8s\n"
    f'    tag: "1.36.2@sha256:{DIGEST_C}"\n'
)

BUCKET_RENDERED = (
    "---\n"
    "# Source: podiumd/templates/zac.yaml\n"
    "apiVersion: apps/v1\n"
    "kind: Deployment\n"
    "metadata:\n"
    "  name: zac\n"
    "spec:\n"
    "  template:\n"
    "    spec:\n"
    "      containers:\n"
    "        - name: zac\n"
    f"          image: ghcr.io/infonl/zac:1.0.0@sha256:{DIGEST_A}\n"
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


def _bucket_upgrade_cache():
    return {
        "ghcr.io/infonl/zac:1.0.0": fresh_upgrade_entry("1.1.0"),
        "maykinmedia/objects-api:1.0.0": fresh_upgrade_entry("1.1.0"),
        "docker.io/alpine/k8s:1.36.2": fresh_upgrade_entry("1.36.3"),
    }


def _setup_bucket_scenario(
    libcvediffcheck: ModuleType, libcvecheck: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, vulns_by_ref
):
    make_chart_dir(tmp_path, BUCKET_VALUES_YAML, BUCKET_CHART_YAML)
    monkeypatch.setattr(libcvediffcheck, "render_chart", fake_render_chart(BUCKET_RENDERED, returncode=0))
    monkeypatch.setattr(libcvediffcheck, "load_upgrade_cache", lambda chart_dir: _bucket_upgrade_cache())
    monkeypatch.setattr(libcvediffcheck, "find_sliding_pins", lambda chart_dir: [])
    monkeypatch.setattr(libcvediffcheck, "registry_tag_exists", lambda host, repo, tag: (False, None))
    monkeypatch.setattr(libcvecheck, "run_trivy", make_run_trivy(vulns_by_ref))


def test_check_cve_diff_splits_own_partner_other_in_order_with_correct_content(
    libcvediffcheck: ModuleType,
    libcvecheck: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    vulns_by_ref = {
        "ghcr.io/infonl/zac:1.0.0": [vuln("CRITICAL", "CVE-OWN-1", "openssl")],
        "ghcr.io/infonl/zac:1.1.0": [],
        "docker.io/maykinmedia/objects-api:1.0.0": [],
        "docker.io/maykinmedia/objects-api:1.1.0": [vuln("HIGH", "CVE-PARTNER-1", "curl")],
        "docker.io/alpine/k8s:1.36.2": [vuln("MEDIUM", "CVE-OTHER-1", "zlib")],
        "docker.io/alpine/k8s:1.36.3": [vuln("MEDIUM", "CVE-OTHER-1", "zlib"), vuln("LOW", "CVE-OTHER-2", "bash")],
    }
    _setup_bucket_scenario(libcvediffcheck, libcvecheck, tmp_path, monkeypatch, vulns_by_ref)

    ok, _detail = libcvediffcheck.check_cve_diff(tmp_path, [])
    assert ok is True

    out = capsys.readouterr().out
    own_i = out.index("--- Own images ---")
    partner_i = out.index("--- Partner-vendor images ---")
    other_i = out.index("--- Other-vendor images ---")
    assert own_i < partner_i < other_i

    own_section = out[own_i:partner_i]
    partner_section = out[partner_i:other_i]
    other_section = out[other_i:]

    assert "ghcr.io/infonl/zac: 1.0.0 -> 1.1.0  [upgrade]" in own_section
    assert "closed: 1 CRIT" in own_section
    assert "ghcr.io/infonl/zac" not in partner_section and "ghcr.io/infonl/zac" not in other_section

    assert "maykinmedia/objects-api: 1.0.0 -> 1.1.0  [upgrade]" in partner_section
    assert "introduced: 1 HIGH" in partner_section
    assert "maykinmedia/objects-api" not in own_section and "maykinmedia/objects-api" not in other_section

    assert "docker.io/alpine/k8s: 1.36.2 -> 1.36.3  [upgrade]" in other_section
    assert "introduced: 1 LOW" in other_section
    assert "docker.io/alpine/k8s" not in own_section and "docker.io/alpine/k8s" not in partner_section


def test_check_cve_diff_bucket_with_no_candidates_prints_no_header(
    libcvediffcheck: ModuleType,
    libcvecheck: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """redis-operator has no upgrade cache entry, so no candidate: no "--- Other-vendor images ---" header."""
    vulns_by_ref = {
        "ghcr.io/infonl/zac:1.0.0": [vuln("CRITICAL", "CVE-OWN-1", "openssl")],
        "ghcr.io/infonl/zac:1.1.0": [],
        "docker.io/maykinmedia/objects-api:1.0.0": [],
        "docker.io/maykinmedia/objects-api:1.1.0": [vuln("HIGH", "CVE-PARTNER-1", "curl")],
    }
    _setup_bucket_scenario(libcvediffcheck, libcvecheck, tmp_path, monkeypatch, vulns_by_ref)
    monkeypatch.setattr(
        libcvediffcheck,
        "load_upgrade_cache",
        lambda chart_dir: {
            "ghcr.io/infonl/zac:1.0.0": fresh_upgrade_entry("1.1.0"),
            "maykinmedia/objects-api:1.0.0": fresh_upgrade_entry("1.1.0"),
            "docker.io/alpine/k8s:1.36.2": fresh_upgrade_entry("1.36.2"),  # no newer tag -- not a candidate
        },
    )

    ok, _detail = libcvediffcheck.check_cve_diff(tmp_path, [])
    assert ok is True

    out = capsys.readouterr().out
    assert "--- Own images ---" in out
    assert "--- Partner-vendor images ---" in out
    assert "--- Other-vendor images ---" not in out


def test_check_cve_diff_summary_reports_correct_per_bucket_counts(
    libcvediffcheck: ModuleType, libcvecheck: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    vulns_by_ref = {
        "ghcr.io/infonl/zac:1.0.0": [vuln("CRITICAL", "CVE-OWN-1", "openssl")],
        "ghcr.io/infonl/zac:1.1.0": [],
        "docker.io/maykinmedia/objects-api:1.0.0": [],
        "docker.io/maykinmedia/objects-api:1.1.0": [vuln("HIGH", "CVE-PARTNER-1", "curl")],
        "docker.io/alpine/k8s:1.36.2": [vuln("MEDIUM", "CVE-OTHER-1", "zlib")],
        "docker.io/alpine/k8s:1.36.3": [vuln("MEDIUM", "CVE-OTHER-1", "zlib"), vuln("LOW", "CVE-OTHER-2", "bash")],
    }
    _setup_bucket_scenario(libcvediffcheck, libcvecheck, tmp_path, monkeypatch, vulns_by_ref)

    ok, detail = libcvediffcheck.check_cve_diff(tmp_path, [])
    assert ok is True
    assert detail == (
        "1 own (1 closed, 0 introduced), "
        "1 partner-vendor (0 closed, 1 introduced), "
        "1 other-vendor (0 closed, 1 introduced); "
        "0 scan error(s)"
    )
