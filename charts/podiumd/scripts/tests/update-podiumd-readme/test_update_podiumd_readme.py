"""main() — the fixer companion to lib.helm_docs_check.check_helm_docs.
No real helm-docs/git invocation happens in these tests — `run` is
monkeypatched, and CHART_DIR points at a disposable tmp_path chart dir."""
from types import SimpleNamespace

import pytest


def result(returncode=0, stdout="", stderr=""):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def make_chart_dir(tmp_path, gotmpl=False):
    (tmp_path / "Chart.yaml").write_text("name: podiumd\nversion: 4.9.0\n", encoding="utf-8")
    (tmp_path / "values.yaml").write_text("foo: bar\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# podiumd\n", encoding="utf-8")
    if gotmpl:
        (tmp_path / "README.md.gotmpl").write_text("{{ template \"chart.header\" . }}\n", encoding="utf-8")
    return tmp_path


def test_helm_docs_not_installed_fails(upr, tmp_path, monkeypatch):
    monkeypatch.setattr(upr, "CHART_DIR", make_chart_dir(tmp_path))
    monkeypatch.setattr(upr.shutil, "which", lambda name: None)
    monkeypatch.setattr(upr.sys, "argv", ["update-podiumd-readme.py"])

    with pytest.raises(SystemExit) as exc_info:
        upr.main()
    assert exc_info.value.code == 1


def test_dry_run_passes_when_in_sync(upr, tmp_path, monkeypatch):
    monkeypatch.setattr(upr, "CHART_DIR", make_chart_dir(tmp_path))
    monkeypatch.setattr(upr.shutil, "which", lambda name: "/usr/bin/helm-docs")
    monkeypatch.setattr(upr, "check_helm_docs", lambda chart_dir: (True, "in sync"))
    monkeypatch.setattr(upr.sys, "argv", ["update-podiumd-readme.py", "--dry-run"])

    with pytest.raises(SystemExit) as exc_info:
        upr.main()
    assert exc_info.value.code == 0


def test_dry_run_fails_on_drift_without_writing(upr, tmp_path, monkeypatch):
    chart_dir = make_chart_dir(tmp_path)
    original = (chart_dir / "README.md").read_text(encoding="utf-8")
    monkeypatch.setattr(upr, "CHART_DIR", chart_dir)
    monkeypatch.setattr(upr.shutil, "which", lambda name: "/usr/bin/helm-docs")
    monkeypatch.setattr(upr, "check_helm_docs", lambda cd: (False, "3 line(s) out of sync"))

    def fail_if_called(cmd, **kw):
        raise AssertionError("--dry-run must never invoke `run` (real helm-docs/git) itself")

    monkeypatch.setattr(upr, "run", fail_if_called)
    monkeypatch.setattr(upr.sys, "argv", ["update-podiumd-readme.py", "--dry-run"])

    with pytest.raises(SystemExit) as exc_info:
        upr.main()
    assert exc_info.value.code == 1
    assert (chart_dir / "README.md").read_text(encoding="utf-8") == original


def test_real_run_helm_docs_failure_fails(upr, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(upr, "CHART_DIR", make_chart_dir(tmp_path))
    monkeypatch.setattr(upr.shutil, "which", lambda name: "/usr/bin/helm-docs")
    monkeypatch.setattr(upr, "run", lambda cmd, **kw: result(returncode=1, stderr="boom"))
    monkeypatch.setattr(upr.sys, "argv", ["update-podiumd-readme.py"])

    with pytest.raises(SystemExit) as exc_info:
        upr.main()
    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "helm-docs failed" in err
    assert "boom" in err


def test_real_run_reports_no_changes(upr, tmp_path, monkeypatch, capsys):
    chart_dir = make_chart_dir(tmp_path)
    readme_content = (chart_dir / "README.md").read_text(encoding="utf-8")
    monkeypatch.setattr(upr, "CHART_DIR", chart_dir)
    monkeypatch.setattr(upr.shutil, "which", lambda name: "/usr/bin/helm-docs")

    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        # the --dry-run probe reproduces the README verbatim -> nothing to write
        return result(stdout=readme_content)

    monkeypatch.setattr(upr, "run", fake_run)
    monkeypatch.setattr(upr.sys, "argv", ["update-podiumd-readme.py"])

    upr.main()

    out = capsys.readouterr().out
    assert "OK: README.md already matched helm-docs output — nothing changed" in out
    assert len(calls) == 1  # only the --dry-run probe — real helm-docs/git never invoked
    assert "--dry-run" in calls[0]


def test_real_run_reports_diff_when_changed(upr, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(upr, "CHART_DIR", make_chart_dir(tmp_path))
    monkeypatch.setattr(upr.shutil, "which", lambda name: "/usr/bin/helm-docs")

    def fake_run(cmd, **kw):
        if cmd[0] == "git":
            return result(stdout=" README.md | 4 +++-\n 1 file changed\n")
        return result()

    monkeypatch.setattr(upr, "run", fake_run)
    monkeypatch.setattr(upr.sys, "argv", ["update-podiumd-readme.py"])

    upr.main()

    out = capsys.readouterr().out
    assert "README.md | 4 +++-" in out
    assert "README.md regenerated — review the diff above and stage it yourself before committing" in out


def test_command_omits_template_files_without_gotmpl(upr, tmp_path, monkeypatch):
    monkeypatch.setattr(upr, "CHART_DIR", make_chart_dir(tmp_path, gotmpl=False))
    monkeypatch.setattr(upr.shutil, "which", lambda name: "/usr/bin/helm-docs")
    captured = []

    def fake_run(cmd, **kw):
        captured.append(cmd)
        return result()

    monkeypatch.setattr(upr, "run", fake_run)
    monkeypatch.setattr(upr.sys, "argv", ["update-podiumd-readme.py"])

    upr.main()

    assert "--template-files" not in captured[0]


def test_command_includes_template_files_with_gotmpl(upr, tmp_path, monkeypatch):
    monkeypatch.setattr(upr, "CHART_DIR", make_chart_dir(tmp_path, gotmpl=True))
    monkeypatch.setattr(upr.shutil, "which", lambda name: "/usr/bin/helm-docs")
    captured = []

    def fake_run(cmd, **kw):
        captured.append(cmd)
        return result()

    monkeypatch.setattr(upr, "run", fake_run)
    monkeypatch.setattr(upr.sys, "argv", ["update-podiumd-readme.py"])

    upr.main()

    assert "--template-files" in captured[0]
    idx = captured[0].index("--template-files")
    assert captured[0][idx + 1] == "README.md.gotmpl"
