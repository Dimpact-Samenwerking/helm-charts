"""run_trivy / check_cves — report-only CVE sweep against every unique
digest-pinned image, via `docker run aquasec/trivy:latest`, cached by
(repository, digest) in charts/podiumd/cve-scan-cache.json — tracked chart
content, not gitignored, so the cache is committed and shared across
contributors/CI. No real docker/trivy invocation happens in these tests —
`run` is mocked throughout."""
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace


def trivy_result(returncode=0, stdout="", stderr=""):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def vuln(severity, cve="CVE-2024-0001", pkg="openssl", fixed="3.0.2"):
    return {"VulnerabilityID": cve, "PkgName": pkg, "Severity": severity, "FixedVersion": fixed}


def make_chart_dir(tmp_path):
    return tmp_path


def write_values(chart_dir, text):
    (chart_dir / "values.yaml").write_text(text, encoding="utf-8")


DIGEST = "a" * 64
PIN = f'a:\n  image:\n    repository: org/repo\n    tag: "1.0.0@sha256:{DIGEST}"\n'


# --- run_trivy ---

def test_run_trivy_parses_vulnerabilities(libcvecheck, monkeypatch):
    output = {"Results": [{"Target": "img", "Vulnerabilities": [vuln("HIGH")]}]}
    monkeypatch.setattr(libcvecheck, "run", lambda cmd, **kw: trivy_result(stdout=json.dumps(output)))
    assert libcvecheck.run_trivy("org/repo:1.0.0") == [vuln("HIGH")]


def test_run_trivy_handles_missing_results_and_vulnerabilities_keys(libcvecheck, monkeypatch):
    monkeypatch.setattr(libcvecheck, "run", lambda cmd, **kw: trivy_result(stdout="{}"))
    assert libcvecheck.run_trivy("org/repo:1.0.0") == []

    output = {"Results": [{"Target": "img"}]}  # no Vulnerabilities key at all
    monkeypatch.setattr(libcvecheck, "run", lambda cmd, **kw: trivy_result(stdout=json.dumps(output)))
    assert libcvecheck.run_trivy("org/repo:1.0.0") == []


def test_run_trivy_unparseable_output_returns_none(libcvecheck, monkeypatch):
    monkeypatch.setattr(libcvecheck, "run", lambda cmd, **kw: trivy_result(returncode=1, stderr="pull failed"))
    assert libcvecheck.run_trivy("org/repo:1.0.0") is None


def test_run_trivy_invokes_expected_docker_command(libcvecheck, monkeypatch):
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        return trivy_result(stdout="{}")

    monkeypatch.setattr(libcvecheck, "run", fake_run)
    libcvecheck.run_trivy("ghcr.io/org/repo:1.0.0")
    assert captured["cmd"] == [
        "docker", "run", "--rm", "aquasec/trivy:latest", "image", "--ignore-unfixed",
        "--scanners", "vuln", "--format", "json", "ghcr.io/org/repo:1.0.0",
    ]


# --- cache_key / cache_entry_is_fresh ---

def test_cache_key_format(libcvecheck):
    assert libcvecheck.cache_key("org/repo", "a" * 64) == f"org/repo@sha256:{'a' * 64}"


def test_cache_entry_is_fresh_within_ttl(libcvecheck):
    entry = {"scanned_at": datetime.now(timezone.utc).isoformat(), "vulnerabilities": []}
    assert libcvecheck.cache_entry_is_fresh(entry) is True


def test_cache_entry_is_fresh_false_when_expired(libcvecheck):
    stale = datetime.now(timezone.utc) - timedelta(days=libcvecheck.CVE_CACHE_TTL_DAYS + 1)
    entry = {"scanned_at": stale.isoformat(), "vulnerabilities": []}
    assert libcvecheck.cache_entry_is_fresh(entry) is False


def test_cache_entry_is_fresh_false_when_malformed(libcvecheck):
    assert libcvecheck.cache_entry_is_fresh({}) is False
    assert libcvecheck.cache_entry_is_fresh({"scanned_at": "not-a-date"}) is False


# --- load_cache / save_cache ---

def test_load_cache_missing_file_returns_empty_dict(libcvecheck, tmp_path):
    chart_dir = make_chart_dir(tmp_path)
    assert libcvecheck.load_cache(chart_dir) == {}


def test_load_cache_corrupted_file_returns_empty_dict(libcvecheck, tmp_path):
    chart_dir = make_chart_dir(tmp_path)
    libcvecheck.cache_path(chart_dir).write_text("not json", encoding="utf-8")
    assert libcvecheck.load_cache(chart_dir) == {}


def test_save_cache_writes_json_directly_under_chart_dir(libcvecheck, tmp_path):
    chart_dir = make_chart_dir(tmp_path)
    libcvecheck.save_cache(chart_dir, {"k": "v"})
    path = libcvecheck.cache_path(chart_dir)
    assert path.is_file()
    assert json.loads(path.read_text(encoding="utf-8")) == {"k": "v"}
    assert path == chart_dir / "cve-scan-cache.json"


# --- check_cves ---

def test_check_cves_no_docker_passes_and_skips(vp, tmp_path, monkeypatch):
    chart_dir = make_chart_dir(tmp_path)
    monkeypatch.setattr(vp.shutil, "which", lambda name: None)
    ok, detail = vp.check_cves(chart_dir)
    assert ok is True
    assert "not installed" in detail


def test_check_cves_no_pins_passes(vp, libcvecheck, tmp_path, monkeypatch):
    chart_dir = make_chart_dir(tmp_path)
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/docker")
    write_values(chart_dir, "a:\n  enabled: true\n")
    ok, detail = vp.check_cves(chart_dir)
    assert ok is True
    assert "0 CVE(s) across 0 image(s)" in detail


def test_check_cves_no_findings_passes(vp, libcvecheck, tmp_path, monkeypatch, capsys):
    chart_dir = make_chart_dir(tmp_path)
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/docker")
    write_values(chart_dir, PIN)
    monkeypatch.setattr(libcvecheck, "run", lambda cmd, **kw: trivy_result(stdout="{}"))
    ok, detail = vp.check_cves(chart_dir)
    assert ok is True
    assert "0 CVE(s) across 1 image(s)" in detail
    out = capsys.readouterr().out
    assert "OK: no known CVEs" in out


def test_check_cves_reports_findings_never_fails(vp, libcvecheck, tmp_path, monkeypatch, capsys):
    chart_dir = make_chart_dir(tmp_path)
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/docker")
    write_values(chart_dir, PIN)
    output = {"Results": [{"Vulnerabilities": [
        vuln("LOW", cve="CVE-2024-0002"),
        vuln("CRITICAL", cve="CVE-2024-0001"),
    ]}]}
    monkeypatch.setattr(libcvecheck, "run", lambda cmd, **kw: trivy_result(stdout=json.dumps(output)))
    ok, detail = vp.check_cves(chart_dir)
    assert ok is True  # never fails regardless of severity
    assert "2 CVE(s) across 1 image(s)" in detail
    out = capsys.readouterr().out
    assert "report-only, never fails" in out
    # CRITICAL sorts before LOW in the printed output.
    assert out.index("CVE-2024-0001") < out.index("CVE-2024-0002")


def test_check_cves_dedupes_repeated_pins(vp, libcvecheck, tmp_path, monkeypatch):
    chart_dir = make_chart_dir(tmp_path)
    write_values(chart_dir, (
        "a:\n  image:\n    repository: org/repo\n"
        f'    tag: "1.0.0@sha256:{DIGEST}"\n'
        "b:\n  image:\n    repository: org/repo\n"
        f'    tag: "1.0.0@sha256:{DIGEST}"\n'
    ))
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/docker")
    calls = {"n": 0}

    def fake_run(cmd, **kw):
        calls["n"] += 1
        return trivy_result(stdout="{}")

    monkeypatch.setattr(libcvecheck, "run", fake_run)
    ok, detail = vp.check_cves(chart_dir)
    assert ok is True
    assert calls["n"] == 1  # same (repository, version) pin scanned once, not twice
    assert "1 image(s)" in detail


def test_check_cves_scan_error_reported_but_still_passes(vp, libcvecheck, tmp_path, monkeypatch, capsys):
    chart_dir = make_chart_dir(tmp_path)
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/docker")
    write_values(chart_dir, PIN)
    monkeypatch.setattr(libcvecheck, "run", lambda cmd, **kw: trivy_result(returncode=1, stdout="not json"))
    ok, detail = vp.check_cves(chart_dir)
    assert ok is True
    assert "1 scan error(s)" in detail
    out = capsys.readouterr().out
    assert "SCAN-ERR" in out


def test_check_cves_skips_unresolved_repository(vp, libcvecheck, tmp_path, monkeypatch):
    chart_dir = make_chart_dir(tmp_path)
    write_values(chart_dir, f'a:\n  image:\n    tag: "1.0.0@sha256:{DIGEST}"\n')  # no repository key
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/docker")
    calls = {"n": 0}

    def fake_run(cmd, **kw):
        calls["n"] += 1
        return trivy_result(stdout="{}")

    monkeypatch.setattr(libcvecheck, "run", fake_run)
    ok, detail = vp.check_cves(chart_dir)
    assert ok is True
    assert calls["n"] == 0
    assert "0 CVE(s) across 0 image(s)" in detail


# --- check_cves caching ---

def test_check_cves_cache_miss_scans_and_persists(vp, libcvecheck, tmp_path, monkeypatch, capsys):
    chart_dir = make_chart_dir(tmp_path)
    write_values(chart_dir, PIN)
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr(libcvecheck, "run", lambda cmd, **kw: trivy_result(
        stdout=json.dumps({"Results": [{"Vulnerabilities": [vuln("HIGH")]}]})))

    ok, detail = vp.check_cves(chart_dir)
    assert ok is True
    assert "0 cached" in detail

    saved = libcvecheck.load_cache(chart_dir)
    key = libcvecheck.cache_key("org/repo", DIGEST)
    assert key in saved
    assert saved[key]["vulnerabilities"] == [vuln("HIGH")]
    assert "scanned_at" in saved[key]

    out = capsys.readouterr().out
    assert "cve-scan-cache.json changed — commit it" in out


def test_check_cves_no_op_when_all_cached_skips_commit_reminder(vp, libcvecheck, tmp_path, monkeypatch, capsys):
    chart_dir = make_chart_dir(tmp_path)
    write_values(chart_dir, PIN)
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/docker")
    key = libcvecheck.cache_key("org/repo", DIGEST)
    libcvecheck.save_cache(chart_dir, {
        key: {"scanned_at": datetime.now(timezone.utc).isoformat(), "vulnerabilities": []},
    })

    def fail_if_called(cmd, **kw):
        raise AssertionError("trivy should not have been invoked — cache hit expected")

    monkeypatch.setattr(libcvecheck, "run", fail_if_called)
    vp.check_cves(chart_dir)
    out = capsys.readouterr().out
    assert "changed — commit it" not in out


def test_check_cves_cache_hit_skips_scanning(vp, libcvecheck, tmp_path, monkeypatch, capsys):
    chart_dir = make_chart_dir(tmp_path)
    write_values(chart_dir, PIN)
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/docker")
    key = libcvecheck.cache_key("org/repo", DIGEST)
    libcvecheck.save_cache(chart_dir, {
        key: {"scanned_at": datetime.now(timezone.utc).isoformat(), "vulnerabilities": [vuln("CRITICAL")]},
    })

    def fail_if_called(cmd, **kw):
        raise AssertionError("trivy should not have been invoked — cache hit expected")

    monkeypatch.setattr(libcvecheck, "run", fail_if_called)
    ok, detail = vp.check_cves(chart_dir)
    assert ok is True
    assert "1 cached" in detail
    assert "1 CVE(s) across 1 image(s)" in detail  # still reported, from cache
    out = capsys.readouterr().out
    assert "1/1 image(s) served from cache" in out


def test_check_cves_expired_cache_entry_rescans(vp, libcvecheck, tmp_path, monkeypatch):
    chart_dir = make_chart_dir(tmp_path)
    write_values(chart_dir, PIN)
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/docker")
    key = libcvecheck.cache_key("org/repo", DIGEST)
    stale = datetime.now(timezone.utc) - timedelta(days=libcvecheck.CVE_CACHE_TTL_DAYS + 1)
    libcvecheck.save_cache(chart_dir, {
        key: {"scanned_at": stale.isoformat(), "vulnerabilities": [vuln("CRITICAL")]},
    })
    calls = {"n": 0}

    def fake_run(cmd, **kw):
        calls["n"] += 1
        return trivy_result(stdout="{}")  # fresh scan finds nothing this time

    monkeypatch.setattr(libcvecheck, "run", fake_run)
    ok, detail = vp.check_cves(chart_dir)
    assert ok is True
    assert calls["n"] == 1  # expired entry triggered a real rescan
    assert "0 cached" in detail
    assert "0 CVE(s)" in detail  # the fresh (empty) result replaced the stale cached one


def test_check_cves_digest_change_invalidates_cache(vp, libcvecheck, tmp_path, monkeypatch):
    chart_dir = make_chart_dir(tmp_path)
    old_digest = "b" * 64
    write_values(chart_dir, PIN)  # pinned to DIGEST ("a" * 64)
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/docker")
    old_key = libcvecheck.cache_key("org/repo", old_digest)
    libcvecheck.save_cache(chart_dir, {
        old_key: {"scanned_at": datetime.now(timezone.utc).isoformat(), "vulnerabilities": [vuln("CRITICAL")]},
    })
    calls = {"n": 0}

    def fake_run(cmd, **kw):
        calls["n"] += 1
        return trivy_result(stdout="{}")

    monkeypatch.setattr(libcvecheck, "run", fake_run)
    ok, detail = vp.check_cves(chart_dir)
    assert ok is True
    assert calls["n"] == 1  # different digest -> different cache key -> cache miss
    assert "0 cached" in detail


def test_check_cves_prunes_entries_for_unpinned_images(vp, libcvecheck, tmp_path, monkeypatch):
    chart_dir = make_chart_dir(tmp_path)
    write_values(chart_dir, PIN)
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/docker")
    stale_key = "org/gone@sha256:" + "c" * 64
    current_key = libcvecheck.cache_key("org/repo", DIGEST)
    libcvecheck.save_cache(chart_dir, {
        stale_key: {"scanned_at": datetime.now(timezone.utc).isoformat(), "vulnerabilities": []},
        current_key: {"scanned_at": datetime.now(timezone.utc).isoformat(), "vulnerabilities": []},
    })
    monkeypatch.setattr(libcvecheck, "run", lambda cmd, **kw: trivy_result(stdout="{}"))

    vp.check_cves(chart_dir)

    saved = libcvecheck.load_cache(chart_dir)
    assert stale_key not in saved
    assert current_key in saved
