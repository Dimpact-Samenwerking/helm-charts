"""run_trivy / check_cves — report-only CVE sweep against every unique
digest-pinned image, via `docker run aquasec/trivy:latest`. No real
docker/trivy invocation happens in these tests — `run` is mocked
throughout."""
import json
from types import SimpleNamespace


def trivy_result(returncode=0, stdout="", stderr=""):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def vuln(severity, cve="CVE-2024-0001", pkg="openssl", fixed="3.0.2"):
    return {"VulnerabilityID": cve, "PkgName": pkg, "Severity": severity, "FixedVersion": fixed}


def write_values(chart_dir, text):
    (chart_dir / "values.yaml").write_text(text, encoding="utf-8")


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


# --- check_cves ---

def test_check_cves_no_docker_passes_and_skips(vp, tmp_path, monkeypatch):
    monkeypatch.setattr(vp.shutil, "which", lambda name: None)
    ok, detail = vp.check_cves(tmp_path)
    assert ok is True
    assert "not installed" in detail


def test_check_cves_no_pins_passes(vp, libcvecheck, tmp_path, monkeypatch):
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/docker")
    write_values(tmp_path, "a:\n  enabled: true\n")
    ok, detail = vp.check_cves(tmp_path)
    assert ok is True
    assert "0 CVE(s) across 0 image(s)" in detail


def test_check_cves_no_findings_passes(vp, libcvecheck, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/docker")
    write_values(tmp_path, (
        "a:\n  image:\n    repository: org/repo\n"
        f'    tag: "1.0.0@sha256:{"a" * 64}"\n'
    ))
    monkeypatch.setattr(libcvecheck, "run", lambda cmd, **kw: trivy_result(stdout="{}"))
    ok, detail = vp.check_cves(tmp_path)
    assert ok is True
    assert "0 CVE(s) across 1 image(s)" in detail
    out = capsys.readouterr().out
    assert "OK: no known CVEs" in out


def test_check_cves_reports_findings_never_fails(vp, libcvecheck, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/docker")
    write_values(tmp_path, (
        "a:\n  image:\n    repository: org/repo\n"
        f'    tag: "1.0.0@sha256:{"a" * 64}"\n'
    ))
    output = {"Results": [{"Vulnerabilities": [
        vuln("LOW", cve="CVE-2024-0002"),
        vuln("CRITICAL", cve="CVE-2024-0001"),
    ]}]}
    monkeypatch.setattr(libcvecheck, "run", lambda cmd, **kw: trivy_result(stdout=json.dumps(output)))
    ok, detail = vp.check_cves(tmp_path)
    assert ok is True  # never fails regardless of severity
    assert "2 CVE(s) across 1 image(s)" in detail
    out = capsys.readouterr().out
    assert "report-only, never fails" in out
    # CRITICAL sorts before LOW in the printed output.
    assert out.index("CVE-2024-0001") < out.index("CVE-2024-0002")


def test_check_cves_dedupes_repeated_pins(vp, libcvecheck, tmp_path, monkeypatch):
    write_values(tmp_path, (
        "a:\n  image:\n    repository: org/repo\n"
        f'    tag: "1.0.0@sha256:{"a" * 64}"\n'
        "b:\n  image:\n    repository: org/repo\n"
        f'    tag: "1.0.0@sha256:{"a" * 64}"\n'
    ))
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/docker")
    calls = {"n": 0}

    def fake_run(cmd, **kw):
        calls["n"] += 1
        return trivy_result(stdout="{}")

    monkeypatch.setattr(libcvecheck, "run", fake_run)
    ok, detail = vp.check_cves(tmp_path)
    assert ok is True
    assert calls["n"] == 1  # same (repository, version) pin scanned once, not twice
    assert "1 image(s)" in detail


def test_check_cves_scan_error_reported_but_still_passes(vp, libcvecheck, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/docker")
    write_values(tmp_path, (
        "a:\n  image:\n    repository: org/repo\n"
        f'    tag: "1.0.0@sha256:{"a" * 64}"\n'
    ))
    monkeypatch.setattr(libcvecheck, "run", lambda cmd, **kw: trivy_result(returncode=1, stdout="not json"))
    ok, detail = vp.check_cves(tmp_path)
    assert ok is True
    assert "1 scan error(s)" in detail
    out = capsys.readouterr().out
    assert "SCAN-ERR" in out


def test_check_cves_skips_unresolved_repository(vp, libcvecheck, tmp_path, monkeypatch):
    write_values(tmp_path, f'a:\n  image:\n    tag: "1.0.0@sha256:{"a" * 64}"\n')  # no repository key
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/docker")
    calls = {"n": 0}

    def fake_run(cmd, **kw):
        calls["n"] += 1
        return trivy_result(stdout="{}")

    monkeypatch.setattr(libcvecheck, "run", fake_run)
    ok, detail = vp.check_cves(tmp_path)
    assert ok is True
    assert calls["n"] == 0
    assert "0 CVE(s) across 0 image(s)" in detail
