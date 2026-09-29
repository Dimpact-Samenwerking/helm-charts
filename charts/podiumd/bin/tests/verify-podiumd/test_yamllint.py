"""Tests for check_yamllint: yamllint on the full `helm template` render.

Raw templates aren't valid YAML (Go template syntax), hence the render. Only own +
structural findings fail; partner-vendor findings print per-item but never fail; other
vendored findings get an aggregate count; cosmetic findings are never reported.
helm/yamllint calls (vp.run) and friendly_vendor_charts are mocked."""

from pathlib import Path
from types import ModuleType
from types import SimpleNamespace

import pytest


def fake_run(returncode=0, stdout="", stderr=""):
    def run(cmd, **kwargs):
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)

    return run


def fake_render_chart(rendered="", returncode=0):
    def render_chart(chart_dir, extra_args):
        return SimpleNamespace(returncode=returncode, stdout=rendered, stderr="")

    return render_chart


def no_friendly_vendors(libyamllintcheck: ModuleType, monkeypatch: pytest.MonkeyPatch):
    """Default to no partner vendors, so vendored findings land in the "other vendor" count."""
    monkeypatch.setattr(libyamllintcheck, "friendly_vendor_charts", lambda chart_dir: {})


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


@pytest.fixture(autouse=True)
def _default_render(libyamllintcheck: ModuleType, monkeypatch: pytest.MonkeyPatch):
    """Default every test to the RENDERED fixture; override render_chart to change it."""
    monkeypatch.setattr(libyamllintcheck, "render_chart", fake_render_chart(RENDERED))


def sequenced_run(yamllint_stdout, yamllint_returncode=1):
    """Fake run() for the yamllint call."""

    def run(cmd, **kwargs):
        return SimpleNamespace(returncode=yamllint_returncode, stdout=yamllint_stdout, stderr="")

    return run


# --- build_line_sources ---


def test_build_line_sources_maps_lines_to_preceding_source_comment(librenderscope: ModuleType):
    sources = librenderscope.build_line_sources(RENDERED)
    assert sources[3] == "podiumd/templates/frankgateway.yaml"
    assert sources[4] == "podiumd/templates/frankgateway.yaml"
    assert sources[7] == "podiumd/charts/zac/templates/configmap.yaml"


def test_build_line_sources_line_before_any_source_is_none(librenderscope: ModuleType):
    sources = librenderscope.build_line_sources(RENDERED)
    assert sources[1] is None


# --- chart_name_from_source ---


def test_chart_name_from_source_extracts_chart_immediately_before_templates(librenderscope: ModuleType):
    assert librenderscope.chart_name_from_source("podiumd/charts/zac/templates/configmap.yaml") == "zac"


def test_chart_name_from_source_uses_deepest_nested_chart(librenderscope: ModuleType):
    path = "podiumd/charts/eck-operator/charts/eck-operator-crds/templates/all-crds.yaml"
    assert librenderscope.chart_name_from_source(path) == "eck-operator-crds"


def test_chart_name_from_source_falls_back_to_raw_string(librenderscope: ModuleType):
    assert librenderscope.chart_name_from_source("no templates segment here") == "no templates segment here"


# --- check_yamllint ---


def test_check_yamllint_no_findings_passes(
    vp: ModuleType, libyamllintcheck: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/yamllint")
    no_friendly_vendors(libyamllintcheck, monkeypatch)
    monkeypatch.setattr(libyamllintcheck, "run", sequenced_run(yamllint_stdout="", yamllint_returncode=0))

    ok, detail = vp.check_yamllint(tmp_path, [])
    assert ok is True
    assert "0 real" in detail


def test_check_yamllint_own_key_duplicate_fails(
    vp: ModuleType, libyamllintcheck: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/yamllint")
    no_friendly_vendors(libyamllintcheck, monkeypatch)
    yamllint_out = '  4:5     error    duplication of key "kind" in mapping  (key-duplicates)\n'
    monkeypatch.setattr(libyamllintcheck, "run", sequenced_run(yamllint_out))

    ok, detail = vp.check_yamllint(tmp_path, [])
    assert ok is False
    assert "1 real" in detail


def test_check_yamllint_finding_line_is_labeled_as_rendered(
    vp: ModuleType,
    libyamllintcheck: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """Finding lines are positions in the rendered output, labelled "rendered line(s)"
    so they aren't mistaken for lines in the source template."""
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/yamllint")
    no_friendly_vendors(libyamllintcheck, monkeypatch)
    yamllint_out = '  4:5     error    duplication of key "kind" in mapping  (key-duplicates)\n'
    monkeypatch.setattr(libyamllintcheck, "run", sequenced_run(yamllint_out))

    vp.check_yamllint(tmp_path, [])
    out = capsys.readouterr().out
    assert "rendered line(s):" in out


def test_check_yamllint_own_cosmetic_not_reported_at_all(
    vp: ModuleType,
    libyamllintcheck: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """Cosmetic own findings are not mentioned in output or detail at all (too noisy)."""
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/yamllint")
    no_friendly_vendors(libyamllintcheck, monkeypatch)
    yamllint_out = "  4:1     error    trailing spaces  (trailing-spaces)\n"
    monkeypatch.setattr(libyamllintcheck, "run", sequenced_run(yamllint_out))

    ok, detail = vp.check_yamllint(tmp_path, [])
    assert ok is True
    assert "cosmetic" not in detail
    assert detail == "0 real (own), 0 partner-vendor, 0 other-vendor"
    out = capsys.readouterr().out
    assert "trailing" not in out
    assert "cosmetic" not in out


def test_check_yamllint_vendored_key_duplicate_never_fails(
    vp: ModuleType,
    libyamllintcheck: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """Vendored findings never fail, even for rules that fail in own templates."""
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/yamllint")
    no_friendly_vendors(libyamllintcheck, monkeypatch)
    yamllint_out = '  8:5     error    duplication of key "kind" in mapping  (key-duplicates)\n'
    monkeypatch.setattr(libyamllintcheck, "run", sequenced_run(yamllint_out))

    ok, detail = vp.check_yamllint(tmp_path, [])
    assert ok is True
    assert "0 real (own)" in detail
    assert "1 other-vendor" in detail
    out = capsys.readouterr().out
    assert "outside this repo's scope" in out
    assert "never a failure" in out


def test_check_yamllint_vendored_findings_reported_as_one_line_count(
    vp: ModuleType,
    libyamllintcheck: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """Non-friendly vendored findings (can be hundreds) are reported as one aggregate count."""
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/yamllint")
    no_friendly_vendors(libyamllintcheck, monkeypatch)
    yamllint_out = (
        "  7:1     warning  missing starting space in comment  (comments)\n"
        "  8:1     error    trailing spaces  (trailing-spaces)\n"
    )
    monkeypatch.setattr(libyamllintcheck, "run", sequenced_run(yamllint_out))

    ok, detail = vp.check_yamllint(tmp_path, [])
    assert ok is True
    assert "0 other-vendor" in detail  # both findings above are cosmetic rules — never counted
    out = capsys.readouterr().out
    assert "(trailing-spaces)" not in out
    assert "(comments)" not in out


def test_check_yamllint_friendly_vendor_finding_reported_per_item_never_fails(
    vp: ModuleType,
    libyamllintcheck: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """A partner-org vendored finding is printed individually but never fails."""
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/yamllint")
    monkeypatch.setattr(libyamllintcheck, "friendly_vendor_charts", lambda chart_dir: {"zac": "Info(NL)"})
    yamllint_out = '  8:5     error    duplication of key "kind" in mapping  (key-duplicates)\n'
    monkeypatch.setattr(libyamllintcheck, "run", sequenced_run(yamllint_out))

    ok, detail = vp.check_yamllint(tmp_path, [])
    assert ok is True
    assert "0 real (own)" in detail
    assert "1 partner-vendor" in detail
    assert "0 other-vendor" in detail
    out = capsys.readouterr().out
    assert "reported for visibility, never a failure" in out
    assert "podiumd/charts/zac/templates/configmap.yaml" in out
    assert "Info(NL)" in out
    assert "duplication of key" in out  # per-item detail, not just a count
    assert "rendered line(s):" in out


def test_check_yamllint_repeated_own_finding_in_one_file_is_grouped(
    vp: ModuleType,
    libyamllintcheck: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    """Repeated hits of one rule in one file print as one grouped line with a count and
    line list, not one [ERROR] line per hit."""
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/yamllint")
    no_friendly_vendors(libyamllintcheck, monkeypatch)
    rendered = (
        "---\n"
        "# Source: podiumd/templates/frankgateway.yaml\n"
        "apiVersion: v1\n"
        "kind: Service\n"
        "metadata:\n"
        "  labels:\n"
        "    app.kubernetes.io/name: podiumd\n"
        "    app.kubernetes.io/name: frankgateway-shim\n"
        "---\n"
        "kind: Deployment\n"
        "metadata:\n"
        "  labels:\n"
        "    app.kubernetes.io/name: podiumd\n"
        "    app.kubernetes.io/name: frankgateway-shim\n"
    )
    yamllint_out = (
        '  8:5      error    duplication of key "app.kubernetes.io/name" in mapping  (key-duplicates)\n'
        '  14:5     error    duplication of key "app.kubernetes.io/name" in mapping  (key-duplicates)\n'
    )
    monkeypatch.setattr(libyamllintcheck, "render_chart", fake_render_chart(rendered))
    monkeypatch.setattr(libyamllintcheck, "run", sequenced_run(yamllint_out))

    ok, detail = vp.check_yamllint(tmp_path, [])
    assert ok is False
    assert "2 real" in detail
    out = capsys.readouterr().out
    assert out.count("[ERROR  ]") == 1  # one grouped line, not two
    assert "x2" in out
    lines = [line.strip() for line in out.splitlines() if line.strip()]
    assert lines[-2:] == ["8", "14"]  # one location per line, not comma-joined


def test_check_yamllint_missing_binary_fails(vp: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(vp.shutil, "which", lambda name: None)
    ok, detail = vp.check_yamllint(tmp_path, [])
    assert ok is False
    assert "not installed" in detail


def test_check_yamllint_render_failure_fails(
    vp: ModuleType, libyamllintcheck: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/yamllint")
    monkeypatch.setattr(libyamllintcheck, "render_chart", fake_render_chart("", returncode=1))
    ok, detail = vp.check_yamllint(tmp_path, [])
    assert ok is False
    assert "failed to render" in detail
