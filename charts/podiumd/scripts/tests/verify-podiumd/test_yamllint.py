"""check_yamllint / build_line_sources / chart_name_from_source — runs
yamllint against the full `helm template` render (never against raw
templates/*.yaml, which contain Go template syntax that isn't valid YAML on
its own) and buckets findings by scope (this chart's own templates/ vs. a
vendored sub-chart under charts/podiumd/charts/*) and by rule (a real
structural problem — key-duplicates, syntax — vs. cosmetic style). Only an
own+real finding fails; everything else is report-only, same spirit as
check_dry. All `helm`/`yamllint` subprocess calls are mocked via vp.run —
no real yamllint or helm invocation happens in these tests."""
from types import SimpleNamespace

import pytest


def fake_run(returncode=0, stdout="", stderr=""):
    def run(cmd, **kwargs):
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)
    return run


RENDERED = (
    "---\n"
    "# Source: podiumd/templates/frankgateway.yaml\n"
    "apiVersion: v1\n"
    "kind: Service\n"
    "---\n"
    "# Source: podiumd/charts/zac/templates/configmap.yaml\n"
    "apiVersion: v1\n"
    "kind: ConfigMap\n"
)
# Line numbers (1-based) of RENDERED:
#  1 ---
#  2 # Source: podiumd/templates/frankgateway.yaml
#  3 apiVersion: v1
#  4 kind: Service
#  5 ---
#  6 # Source: podiumd/charts/zac/templates/configmap.yaml
#  7 apiVersion: v1
#  8 kind: ConfigMap


def sequenced_run(yamllint_stdout, yamllint_returncode=1, rendered=RENDERED):
    def run(cmd, **kwargs):
        if cmd[0] == "yamllint":
            return SimpleNamespace(returncode=yamllint_returncode, stdout=yamllint_stdout, stderr="")
        if "--help" in cmd:
            return SimpleNamespace(returncode=0, stdout="", stderr="")  # no --skip-schema-validation
        return SimpleNamespace(returncode=0, stdout=rendered, stderr="")  # helm template
    return run


# --- build_line_sources ---

def test_build_line_sources_maps_lines_to_preceding_source_comment(vp):
    sources = vp.build_line_sources(RENDERED)
    assert sources[3] == "podiumd/templates/frankgateway.yaml"
    assert sources[4] == "podiumd/templates/frankgateway.yaml"
    assert sources[7] == "podiumd/charts/zac/templates/configmap.yaml"


def test_build_line_sources_line_before_any_source_is_none(vp):
    sources = vp.build_line_sources(RENDERED)
    assert sources[1] is None


# --- chart_name_from_source ---

def test_chart_name_from_source_extracts_chart_immediately_before_templates(vp):
    assert vp.chart_name_from_source("podiumd/charts/zac/templates/configmap.yaml") == "zac"


def test_chart_name_from_source_uses_deepest_nested_chart(vp):
    path = "podiumd/charts/eck-operator/charts/eck-operator-crds/templates/all-crds.yaml"
    assert vp.chart_name_from_source(path) == "eck-operator-crds"


def test_chart_name_from_source_falls_back_to_raw_string(vp):
    assert vp.chart_name_from_source("no templates segment here") == "no templates segment here"


# --- check_yamllint ---

def test_check_yamllint_no_findings_passes(vp, tmp_path, monkeypatch):
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/yamllint")
    monkeypatch.setattr(vp, "run", sequenced_run(yamllint_stdout="", yamllint_returncode=0))

    ok, detail = vp.check_yamllint(tmp_path, [])
    assert ok is True
    assert "0 real" in detail


def test_check_yamllint_own_key_duplicate_fails(vp, tmp_path, monkeypatch):
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/yamllint")
    yamllint_out = '  4:5     error    duplication of key "kind" in mapping  (key-duplicates)\n'
    monkeypatch.setattr(vp, "run", sequenced_run(yamllint_out))

    ok, detail = vp.check_yamllint(tmp_path, [])
    assert ok is False
    assert "1 real" in detail


def test_check_yamllint_own_cosmetic_does_not_fail(vp, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/yamllint")
    yamllint_out = "  4:1     error    trailing spaces  (trailing-spaces)\n"
    monkeypatch.setattr(vp, "run", sequenced_run(yamllint_out))

    ok, detail = vp.check_yamllint(tmp_path, [])
    assert ok is True
    assert "1 cosmetic" in detail
    out = capsys.readouterr().out
    assert "not a failure" in out
    assert "not shown" in out  # no per-finding dump — too noisy, per project decision


def test_check_yamllint_vendored_key_duplicate_never_fails(vp, tmp_path, monkeypatch, capsys):
    """Even a rule that would fail if found in our own templates must never
    fail the check when it's in a vendored sub-chart — we don't control
    that content, per project policy."""
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/yamllint")
    yamllint_out = '  8:5     error    duplication of key "kind" in mapping  (key-duplicates)\n'
    monkeypatch.setattr(vp, "run", sequenced_run(yamllint_out))

    ok, detail = vp.check_yamllint(tmp_path, [])
    assert ok is True
    assert "0 real (own)" in detail
    assert "1 in vendored" in detail
    out = capsys.readouterr().out
    assert "outside this repo's scope" in out
    assert "never a failure" in out


def test_check_yamllint_vendored_findings_reported_as_one_line_count(vp, tmp_path, monkeypatch, capsys):
    """Vendored findings are noisy (can be hundreds) and not actionable —
    reported as a single aggregate count, never dumped finding-by-finding."""
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/yamllint")
    yamllint_out = (
        "  7:1     warning  missing starting space in comment  (comments)\n"
        "  8:1     error    trailing spaces  (trailing-spaces)\n"
    )
    monkeypatch.setattr(vp, "run", sequenced_run(yamllint_out))

    ok, detail = vp.check_yamllint(tmp_path, [])
    assert ok is True
    assert "2 in vendored" in detail
    out = capsys.readouterr().out
    assert "2 yamllint finding(s) across 1 vendored sub-chart(s)" in out
    assert "(trailing-spaces)" not in out
    assert "(comments)" not in out


def test_check_yamllint_missing_binary_fails(vp, tmp_path, monkeypatch):
    monkeypatch.setattr(vp.shutil, "which", lambda name: None)
    ok, detail = vp.check_yamllint(tmp_path, [])
    assert ok is False
    assert "not installed" in detail


def test_check_yamllint_render_failure_fails(vp, tmp_path, monkeypatch):
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/yamllint")

    def run(cmd, **kwargs):
        if "--help" in cmd:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=1, stdout="", stderr="Error: broke")

    monkeypatch.setattr(vp, "run", run)
    ok, detail = vp.check_yamllint(tmp_path, [])
    assert ok is False
    assert "failed to render" in detail
