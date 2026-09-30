"""check_lint, check_render, report_largest_templates, report_errors_by_subchart,
with helm/git subprocess calls mocked via vp.run (no tools or network needed)."""

import json

from pathlib import Path
from types import ModuleType
from types import SimpleNamespace

import pytest


def fake_run(returncode=0, stdout="", stderr=""):
    def _run(cmd, **kwargs):
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)

    return _run


def fake_render_chart(returncode=0, stdout="", stderr=""):
    """Mock vp's own render_chart binding; render_chart's caching is tested separately."""

    def _render_chart(chart_dir, extra_args):
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)

    return _render_chart


# --- check_lint ---


def test_check_lint_passes_on_clean_output(vp: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(vp, "run", fake_run(0, "1 chart(s) linted, 0 chart(s) failed\n", ""))
    ok, detail = vp.check_lint(tmp_path, [])
    assert ok is True
    assert detail == "0 error(s), 0 warning(s)"


def test_check_lint_fails_on_error_count(vp: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(vp, "run", fake_run(0, "[ERROR] values.yaml: bad\n", ""))
    ok, detail = vp.check_lint(tmp_path, [])
    assert ok is False
    assert "1 error(s)" in detail


def test_check_lint_fails_on_nonzero_returncode(vp: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(vp, "run", fake_run(1, "", "boom"))
    ok, _ = vp.check_lint(tmp_path, [])
    assert ok is False


def test_check_lint_counts_warnings_without_failing(vp: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(vp, "run", fake_run(0, "[WARNING] Chart.yaml: icon is recommended\n", ""))
    ok, detail = vp.check_lint(tmp_path, [])
    assert ok is True
    assert "1 warning(s)" in detail


# --- check_render ---


def test_check_render_success(vp: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    rendered = (
        "---\n# Source: podiumd/templates/a.yaml\nkind: Foo\n---\n# Source: podiumd/templates/b.yaml\nkind: Bar\n"
    )
    monkeypatch.setattr(vp, "render_chart", fake_render_chart(0, rendered, ""))
    ok, detail = vp.check_render(tmp_path, [])
    assert ok is True
    assert detail == "2 manifests"


def test_check_render_failure_reports_error(vp: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(vp, "render_chart", fake_render_chart(1, "", "Error: something broke"))
    ok, detail = vp.check_render(tmp_path, [])
    assert ok is False
    assert "failed to render" in detail


def test_check_render_failure_counts_errors_from_stderr_only(
    vp: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """A failed `helm template --debug` still prints rendered resources to
    stdout; their "# Source:" lines and any "/templates/" string in a
    resource body must not count as errors for that chart."""
    stdout = (
        "---\n# Source: podiumd/charts/openzaak/templates/cm.yaml\n"
        'data: {x: "podiumd/charts/openzaak/templates/other.yaml"}\n'
    )
    stderr = "Error: YAML parse error on podiumd/charts/zac/templates/a.yaml: broke\n"
    monkeypatch.setattr(vp, "render_chart", fake_render_chart(1, stdout, stderr))
    ok, _detail = vp.check_render(tmp_path, [])
    assert ok is False
    out = capsys.readouterr().out
    assert "zac: 1" in out
    assert "openzaak" not in out.split("Errors by sub-chart:")[1]


def test_check_render_zero_manifests_fails(vp: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(vp, "render_chart", fake_render_chart(0, "", ""))
    ok, detail = vp.check_render(tmp_path, [])
    assert ok is False
    assert "0 manifests" in detail


# --- report_largest_templates / report_errors_by_subchart (smoke tests) ---


def test_report_largest_templates_output(vp: ModuleType, capsys: pytest.CaptureFixture[str]):
    text = "# Source: a.yaml\nline\nline\n# Source: b.yaml\nline\n"
    vp.report_largest_templates(text, 5)
    out = capsys.readouterr().out
    assert "a.yaml" in out and "b.yaml" in out


def test_report_largest_templates_no_sources_prints_nothing(vp: ModuleType, capsys: pytest.CaptureFixture[str]):
    vp.report_largest_templates("no source markers here", 5)
    assert capsys.readouterr().out == ""


def test_report_errors_by_subchart_groups_by_chart(vp: ModuleType, capsys: pytest.CaptureFixture[str]):
    text = "Error: zac/templates/a.yaml:1\nError: zac/templates/b.yaml:2\nError: openzaak/templates/c.yaml:1\n"
    vp.report_errors_by_subchart(text)
    out = capsys.readouterr().out
    assert "zac: 2" in out
    assert "openzaak: 1" in out


# --- build_resource_locations / resource_line ---
# Adds a "(rendered line N)" hint for tools that report no line number.


def test_build_resource_locations_maps_kind_name_to_start_line(librenderscope: ModuleType):
    rendered = "---\n# Source: podiumd/templates/a.yaml\napiVersion: v1\nkind: Service\nmetadata:\n  name: foo\n"
    locations = librenderscope.build_resource_locations(rendered)
    assert locations == {("Service", "", "foo"): 3}


def test_build_resource_locations_captures_namespace(librenderscope: ModuleType):
    rendered = (
        "---\n"
        "# Source: podiumd/templates/a.yaml\n"
        "apiVersion: v1\n"
        "kind: Service\n"
        "metadata:\n"
        "  name: foo\n"
        "  namespace: podiumd\n"
    )
    locations = librenderscope.build_resource_locations(rendered)
    assert locations == {("Service", "podiumd", "foo"): 3}


def test_build_resource_locations_skips_resource_without_name(librenderscope: ModuleType):
    rendered = "---\n# Source: podiumd/templates/a.yaml\nkind: Service\n"
    assert librenderscope.build_resource_locations(rendered) == {}


def test_build_resource_locations_multiple_documents(librenderscope: ModuleType):
    rendered = (
        "---\n"
        "# Source: podiumd/templates/a.yaml\n"
        "kind: Service\n"
        "metadata:\n"
        "  name: foo\n"
        "---\n"
        "# Source: podiumd/templates/b.yaml\n"
        "kind: ConfigMap\n"
        "metadata:\n"
        "  name: bar\n"
    )
    locations = librenderscope.build_resource_locations(rendered)
    assert locations[("Service", "", "foo")] == 3
    assert locations[("ConfigMap", "", "bar")] == 8


def test_resource_line_exact_match_with_namespace(librenderscope: ModuleType):
    locations = {("Service", "podiumd", "foo"): 3, ("Service", "other-ns", "foo"): 9}
    assert librenderscope.resource_line(locations, "Service", "foo", namespace="podiumd") == 3
    assert librenderscope.resource_line(locations, "Service", "foo", namespace="other-ns") == 9


def test_resource_line_falls_back_to_kind_name_when_unique(librenderscope: ModuleType):
    locations = {("Service", "", "foo"): 3}
    assert librenderscope.resource_line(locations, "Service", "foo") == 3


def test_resource_line_none_when_ambiguous_across_namespaces(librenderscope: ModuleType):
    """Without a namespace, kind+name in two namespaces must not guess: a wrong line is
    worse than no hint."""
    locations = {("Service", "ns-a", "foo"): 3, ("Service", "ns-b", "foo"): 9}
    assert librenderscope.resource_line(locations, "Service", "foo") is None


def test_resource_line_none_when_not_found(librenderscope: ModuleType):
    locations = {("Service", "", "foo"): 3}
    assert librenderscope.resource_line(locations, "ConfigMap", "bar") is None


# --- render_chart ---
# render_chart calls lib.render_scope's own `run`, so patch librenderscope, not vp.


@pytest.fixture(autouse=True)
def _clear_render_cache(librenderscope: ModuleType):
    """Clear render_chart's module-level cache so cached renders don't leak between tests
    (librenderscope is session-scoped)."""
    librenderscope._render_cache.clear()
    yield
    librenderscope._render_cache.clear()


def _sequenced_run(rendered, returncode=0, stderr=""):
    def _run(cmd, **kwargs):
        return SimpleNamespace(returncode=returncode, stdout=rendered, stderr=stderr)

    return _run


def test_render_chart_returns_helm_templates_result(
    librenderscope: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    rendered = "---\n# Source: podiumd/templates/a.yaml\nkind: Foo\n"
    monkeypatch.setattr(librenderscope, "run", _sequenced_run(rendered))
    result = librenderscope.render_chart(tmp_path, [])
    assert result.returncode == 0
    assert result.stdout == rendered


def test_render_chart_passes_extra_args_through(
    librenderscope: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    captured = {}

    def _run(cmd, **kwargs):
        captured["cmd"] = cmd
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(librenderscope, "run", _run)
    librenderscope.render_chart(tmp_path, ["-f", "values.yaml"])
    assert "-f" in captured["cmd"] and "values.yaml" in captured["cmd"]


def test_render_chart_propagates_failure(librenderscope: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(librenderscope, "run", _sequenced_run("", returncode=1, stderr="Error: broke"))
    result = librenderscope.render_chart(tmp_path, [])
    assert result.returncode == 1
    assert "broke" in result.stderr


def test_render_chart_caches_repeat_calls_with_identical_args(
    librenderscope: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Identical (chart_dir, extra_args) must run the subprocess only once."""
    calls = []

    def _run(cmd, **kwargs):
        calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout="rendered", stderr="")

    monkeypatch.setattr(librenderscope, "run", _run)

    first = librenderscope.render_chart(tmp_path, ["-f", "values.yaml"])
    second = librenderscope.render_chart(tmp_path, ["-f", "values.yaml"])

    assert len(calls) == 1
    assert first is second


def test_render_chart_caches_a_failure_too_not_just_success(
    librenderscope: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Failures are memoized too: a retry within one run would fail identically."""
    calls = []

    def _run(cmd, **kwargs):
        calls.append(cmd)
        return SimpleNamespace(returncode=1, stdout="", stderr="Error: broke")

    monkeypatch.setattr(librenderscope, "run", _run)

    first = librenderscope.render_chart(tmp_path, [])
    second = librenderscope.render_chart(tmp_path, [])

    assert len(calls) == 1
    assert first is second
    assert second.returncode == 1


def test_render_chart_different_extra_args_is_a_distinct_cache_entry(
    librenderscope: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Different extra_args must not reuse another call's cached result."""
    calls = []

    def _run(cmd, **kwargs):
        calls.append(list(cmd))
        return SimpleNamespace(returncode=0, stdout=f"rendered for {cmd}", stderr="")

    monkeypatch.setattr(librenderscope, "run", _run)

    first = librenderscope.render_chart(tmp_path, [])
    second = librenderscope.render_chart(tmp_path, ["-f", "values.yaml"])

    assert len(calls) == 2
    assert first.stdout != second.stdout

    # each one's repeat is still served from its own cache entry
    librenderscope.render_chart(tmp_path, [])
    librenderscope.render_chart(tmp_path, ["-f", "values.yaml"])
    assert len(calls) == 2


# --- render consolidation cross-check ---
# Checks sharing render_chart back to back must make exactly one `helm template` call.


def test_render_consolidation_one_real_render_across_three_checks(
    vp: ModuleType,
    librenderscope: ModuleType,
    libyamllintcheck: ModuleType,
    libkubeconformcheck: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    rendered = "---\n# Source: podiumd/templates/a.yaml\nkind: ConfigMap\n"
    calls = []

    def _run(cmd, **kwargs):
        calls.append(cmd)
        return SimpleNamespace(returncode=0, stdout=rendered, stderr="")

    monkeypatch.setattr(librenderscope, "run", _run)
    monkeypatch.setattr(vp.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(libyamllintcheck, "run", lambda cmd, **kw: SimpleNamespace(returncode=0, stdout="", stderr=""))
    monkeypatch.setattr(libyamllintcheck, "friendly_vendor_charts", lambda chart_dir: {})
    monkeypatch.setattr(
        libkubeconformcheck,
        "run",
        lambda cmd, **kw: SimpleNamespace(returncode=0, stdout=json.dumps({"resources": [], "summary": {}}), stderr=""),
    )
    monkeypatch.setattr("lib.render_scope.friendly_vendor_charts", lambda chart_dir: {})

    extra_args = []
    ok1, _ = vp.check_render(tmp_path, extra_args)
    ok2, _ = vp.check_yamllint(tmp_path, extra_args)
    ok3, _ = vp.check_kubeconform(tmp_path, extra_args)

    assert (ok1, ok2, ok3) == (True, True, True)
    render_calls = [c for c in calls if c[:2] == ["helm", "template"]]
    assert len(render_calls) == 1


# --- lint_args_for (vp.lint_args_for re-export: see test_misc.py) ---


def test_lint_args_for_lives_in_render_scope(librenderscope: ModuleType, tmp_path: Path):
    (tmp_path / "ci").mkdir()
    (tmp_path / "ci" / "lint-values.yaml").write_text("foo: bar\n")
    assert librenderscope.lint_args_for(tmp_path) == ["-f", str(tmp_path / "ci" / "lint-values.yaml")]
