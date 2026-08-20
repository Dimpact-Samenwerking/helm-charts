"""die, require_helm, resolve_chart_dir, lint_args_for, print_summary — the
small orchestration helpers not covered elsewhere."""
import pytest


def test_die_exits_nonzero_and_prints_to_stderr(vp, capsys):
    with pytest.raises(SystemExit) as exc_info:
        vp.die("something broke")
    assert exc_info.value.code == 1
    assert "FAIL: something broke" in capsys.readouterr().err


def test_require_helm_passes_when_helm_present(vp, monkeypatch):
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/helm")
    vp.require_helm()  # must not raise


def test_require_helm_dies_when_helm_missing(vp, monkeypatch):
    monkeypatch.setattr(vp.shutil, "which", lambda name: None)
    with pytest.raises(SystemExit):
        vp.require_helm()


def test_resolve_chart_dir_returns_dir_with_chart_yaml(vp, tmp_path, monkeypatch):
    (tmp_path / "Chart.yaml").write_text("name: podiumd\nversion: 4.9.0\n")
    monkeypatch.setattr(vp, "DEFAULT_CHART_DIR", tmp_path)
    assert vp.resolve_chart_dir() == tmp_path.resolve()


def test_resolve_chart_dir_dies_without_chart_yaml(vp, tmp_path, monkeypatch):
    monkeypatch.setattr(vp, "DEFAULT_CHART_DIR", tmp_path)
    with pytest.raises(SystemExit):
        vp.resolve_chart_dir()


def test_lint_args_for_uses_ci_values_when_present(vp, tmp_path):
    (tmp_path / "ci").mkdir()
    (tmp_path / "ci" / "lint-values.yaml").write_text("foo: bar\n")
    args = vp.lint_args_for(tmp_path)
    assert args == ["-f", str(tmp_path / "ci" / "lint-values.yaml")]


def test_lint_args_for_falls_back_without_ci_values(vp, tmp_path, capsys):
    args = vp.lint_args_for(tmp_path)
    assert args == []
    assert "WARNING" in capsys.readouterr().out


def test_print_summary_all_pass(vp, capsys):
    results = [("Lint", True, "0 errors"), ("Render", True, "257 manifests")]
    vp.print_summary(results, overall_ok=True)
    out = capsys.readouterr().out
    assert "Lint" in out and "PASS" in out
    assert "All checks passed." in out


def test_print_summary_reports_failure(vp, capsys):
    results = [("Lint", False, "1 error")]
    vp.print_summary(results, overall_ok=False)
    out = capsys.readouterr().out
    assert "FAIL" in out
    assert "One or more checks failed" in out
