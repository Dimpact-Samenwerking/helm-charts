"""check_lint, check_render, check_dependencies, supports_skip_schema_validation,
report_largest_templates, report_errors_by_subchart — with `helm`/`git`
subprocess calls mocked out via vp.run, so these tests need neither tool
installed nor network access."""
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

def test_supports_skip_schema_validation_true(vp, monkeypatch):
    monkeypatch.setattr(vp, "run", fake_run(0, "... --skip-schema-validation ...", ""))
    assert vp.supports_skip_schema_validation() is True


def test_supports_skip_schema_validation_false(vp, monkeypatch):
    monkeypatch.setattr(vp, "run", fake_run(0, "no such flag documented here", ""))
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


# --- check_dependencies ---

def test_check_dependencies_success(vp, tmp_path, monkeypatch):
    dep_list_output = "NAME\tVERSION\tREPOSITORY\tSTATUS\na\t1.0\t@x\tok\nb\t2.0\t@x\tok\n"

    def sequenced_run(cmd, **kwargs):
        if cmd[2] == "update":
            # real `helm dependency update` (re-)creates charts/*.tgz; the
            # function rm -rf's the old charts/ dir first, so the mock must
            # simulate that side effect for the later glob() count to match
            charts_dir = tmp_path / "charts"
            charts_dir.mkdir()
            (charts_dir / "a.tgz").touch()
            (charts_dir / "b.tgz").touch()
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout=dep_list_output, stderr="")

    monkeypatch.setattr(vp, "run", sequenced_run)
    ok, detail = vp.check_dependencies(tmp_path)
    assert ok is True
    assert "2 dependencies bundled" in detail


def test_check_dependencies_update_failure(vp, tmp_path, monkeypatch):
    monkeypatch.setattr(vp, "run", fake_run(1, "", "network error"))
    ok, detail = vp.check_dependencies(tmp_path)
    assert ok is False
    assert "update failed" in detail


def test_check_dependencies_count_mismatch(vp, tmp_path, monkeypatch):
    (tmp_path / "charts").mkdir()
    # only one .tgz on disk but the dependency list reports two

    def sequenced_run(cmd, **kwargs):
        if cmd[2] == "update":
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout="NAME\tVERSION\tSTATUS\na\t1.0\tok\nb\t2.0\tok\n", stderr="")

    monkeypatch.setattr(vp, "run", sequenced_run)
    ok, detail = vp.check_dependencies(tmp_path)
    assert ok is False
    assert "expected 2 bundled" in detail


def test_check_dependencies_bad_status_fails(vp, tmp_path, monkeypatch):
    def sequenced_run(cmd, **kwargs):
        if cmd[2] == "update":
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout="NAME\tVERSION\tSTATUS\na\t1.0\tfailed\n", stderr="")

    monkeypatch.setattr(vp, "run", sequenced_run)
    ok, detail = vp.check_dependencies(tmp_path)
    assert ok is False
    assert "did not resolve" in detail
