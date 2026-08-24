"""check_lint, check_render, supports_skip_schema_validation,
report_largest_templates, report_errors_by_subchart — with `helm`/`git`
subprocess calls mocked out via vp.run, so these tests need neither tool
installed nor network access. check_dependencies now lives in
lib.dependencies (also used by set-image-digests.py) — see
tests/lib/test_dependencies.py."""
from types import SimpleNamespace


def fake_run(returncode=0, stdout="", stderr=""):
    def _run(cmd, **kwargs):
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)
    return _run


# --- check_lint ---

def test_check_lint_passes_on_clean_output(vp, tmp_path, monkeypatch):
    monkeypatch.setattr(vp, "run", fake_run(0, "1 chart(s) linted, 0 chart(s) failed\n", ""))
    ok, detail = vp.check_lint(tmp_path, [])
    assert ok is True
    assert detail == "0 error(s), 0 warning(s)"


def test_check_lint_fails_on_error_count(vp, tmp_path, monkeypatch):
    monkeypatch.setattr(vp, "run", fake_run(0, "[ERROR] values.yaml: bad\n", ""))
    ok, detail = vp.check_lint(tmp_path, [])
    assert ok is False
    assert "1 error(s)" in detail


def test_check_lint_fails_on_nonzero_returncode(vp, tmp_path, monkeypatch):
    monkeypatch.setattr(vp, "run", fake_run(1, "", "boom"))
    ok, _ = vp.check_lint(tmp_path, [])
    assert ok is False


def test_check_lint_counts_warnings_without_failing(vp, tmp_path, monkeypatch):
    monkeypatch.setattr(vp, "run", fake_run(0, "[WARNING] Chart.yaml: icon is recommended\n", ""))
    ok, detail = vp.check_lint(tmp_path, [])
    assert ok is True
    assert "1 warning(s)" in detail


# --- supports_skip_schema_validation ---

def test_supports_skip_schema_validation_true(vp, librenderscope, monkeypatch):
    # supports_skip_schema_validation lives in lib.render_scope and calls its
    # OWN `run` binding — vp.run only affects code verify-podiumd.py itself
    # resolves `run` for (check_lint/check_render), so this needs
    # librenderscope, not vp, as the monkeypatch target.
    monkeypatch.setattr(librenderscope, "run", fake_run(0, "... --skip-schema-validation ...", ""))
    assert vp.supports_skip_schema_validation() is True


def test_supports_skip_schema_validation_false(vp, librenderscope, monkeypatch):
    monkeypatch.setattr(librenderscope, "run", fake_run(0, "no such flag documented here", ""))
    assert vp.supports_skip_schema_validation() is False


# --- check_render ---

def test_check_render_success(vp, tmp_path, monkeypatch):
    rendered = "---\n# Source: podiumd/templates/a.yaml\nkind: Foo\n---\n# Source: podiumd/templates/b.yaml\nkind: Bar\n"
    monkeypatch.setattr(vp, "supports_skip_schema_validation", lambda: True)
    monkeypatch.setattr(vp, "run", fake_run(0, rendered, ""))
    ok, detail = vp.check_render(tmp_path, [])
    assert ok is True
    assert detail == "2 manifests"


def test_check_render_failure_reports_error(vp, tmp_path, monkeypatch):
    monkeypatch.setattr(vp, "supports_skip_schema_validation", lambda: True)
    monkeypatch.setattr(vp, "run", fake_run(1, "", "Error: something broke"))
    ok, detail = vp.check_render(tmp_path, [])
    assert ok is False
    assert "failed to render" in detail


def test_check_render_zero_manifests_fails(vp, tmp_path, monkeypatch):
    monkeypatch.setattr(vp, "supports_skip_schema_validation", lambda: True)
    monkeypatch.setattr(vp, "run", fake_run(0, "", ""))
    ok, detail = vp.check_render(tmp_path, [])
    assert ok is False
    assert "0 manifests" in detail


def test_check_render_falls_back_gracefully_without_skip_schema_validation(vp, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(vp, "supports_skip_schema_validation", lambda: False)
    monkeypatch.setattr(vp, "run", fake_run(0, "---\n# Source: a.yaml\nkind: Foo\n", ""))
    ok, detail = vp.check_render(tmp_path, [])
    assert ok is True
    assert "WARNING" in capsys.readouterr().out


# --- report_largest_templates / report_errors_by_subchart (just check they don't crash and print something sensible) ---

def test_report_largest_templates_output(vp, capsys):
    text = "# Source: a.yaml\nline\nline\n# Source: b.yaml\nline\n"
    vp.report_largest_templates(text)
    out = capsys.readouterr().out
    assert "a.yaml" in out and "b.yaml" in out


def test_report_largest_templates_no_sources_prints_nothing(vp, capsys):
    vp.report_largest_templates("no source markers here")
    assert capsys.readouterr().out == ""


def test_report_errors_by_subchart_groups_by_chart(vp, capsys):
    text = "Error: zac/templates/a.yaml:1\nError: zac/templates/b.yaml:2\nError: openzaak/templates/c.yaml:1\n"
    vp.report_errors_by_subchart(text)
    out = capsys.readouterr().out
    assert "zac: 2" in out
    assert "openzaak: 1" in out
