"""check_helm_docs — verifies README.md against values.yaml via a real
`helm-docs --dry-run` regen, diffed against the actual file without ever
writing to it. No real helm-docs binary is invoked in these tests — `run`
is mocked throughout."""
from types import SimpleNamespace


def helm_docs_result(stdout, returncode=0, stderr=""):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


README_CONTENT = "# podiumd\n\nPodiumD Helm chart\n\n## Values\n\n| Key | Type | Default | Description |\n"


def make_chart_dir(tmp_path, readme=README_CONTENT, gotmpl=None):
    (tmp_path / "Chart.yaml").write_text("name: podiumd\nversion: 4.9.0\n", encoding="utf-8")
    (tmp_path / "values.yaml").write_text("foo: bar\n", encoding="utf-8")
    if readme is not None:
        (tmp_path / "README.md").write_text(readme, encoding="utf-8")
    if gotmpl is not None:
        (tmp_path / "README.md.gotmpl").write_text(gotmpl, encoding="utf-8")
    return tmp_path


def test_helm_docs_not_installed_fails(vp, tmp_path, monkeypatch):
    chart_dir = make_chart_dir(tmp_path)
    monkeypatch.setattr(vp.shutil, "which", lambda name: None)
    ok, detail = vp.check_helm_docs(chart_dir)
    assert ok is False
    assert "not installed" in detail


def test_readme_missing_fails(libhelmdocscheck, vp, tmp_path, monkeypatch):
    chart_dir = make_chart_dir(tmp_path, readme=None)
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/helm-docs")
    ok, detail = vp.check_helm_docs(chart_dir)
    assert ok is False
    assert "does not exist" in detail
    assert "fix-podiumd-readme" in detail


def test_helm_docs_command_failure_fails(libhelmdocscheck, vp, tmp_path, monkeypatch):
    chart_dir = make_chart_dir(tmp_path)
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/helm-docs")
    monkeypatch.setattr(libhelmdocscheck, "run",
                         lambda cmd, **kw: helm_docs_result("", returncode=1, stderr="boom"))
    ok, detail = vp.check_helm_docs(chart_dir)
    assert ok is False
    assert "helm-docs failed" in detail
    assert "boom" in detail


def test_in_sync_passes(libhelmdocscheck, vp, tmp_path, monkeypatch, capsys):
    chart_dir = make_chart_dir(tmp_path)
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/helm-docs")
    monkeypatch.setattr(libhelmdocscheck, "run", lambda cmd, **kw: helm_docs_result(README_CONTENT))

    ok, detail = vp.check_helm_docs(chart_dir)
    assert ok is True
    assert detail == "in sync"
    assert "OK: README.md matches helm-docs output" in capsys.readouterr().out


def test_drift_fails_and_reports_changed_line_count(libhelmdocscheck, vp, tmp_path, monkeypatch, capsys):
    chart_dir = make_chart_dir(tmp_path)
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/helm-docs")
    regenerated = README_CONTENT + "| newkey | string | `\"x\"` |  |\n"
    monkeypatch.setattr(libhelmdocscheck, "run", lambda cmd, **kw: helm_docs_result(regenerated))

    ok, detail = vp.check_helm_docs(chart_dir)
    assert ok is False
    assert detail == "1 line(s) out of sync — run fix-podiumd-readme"
    out = capsys.readouterr().out
    assert "DRIFT" in out
    assert "1 line(s) would change" in out


def test_drift_shows_actual_diff_lines_not_just_a_count(libhelmdocscheck, vp, tmp_path, monkeypatch, capsys):
    """The finding must be actionable on its own — show WHICH line(s)
    changed (a real unified diff), not just how many."""
    chart_dir = make_chart_dir(tmp_path)
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/helm-docs")
    regenerated = README_CONTENT.replace("PodiumD Helm chart", "PodiumD Helm chart (updated)")
    monkeypatch.setattr(libhelmdocscheck, "run", lambda cmd, **kw: helm_docs_result(regenerated))

    ok, detail = vp.check_helm_docs(chart_dir)
    assert ok is False
    out = capsys.readouterr().out
    assert "-PodiumD Helm chart" in out
    assert "+PodiumD Helm chart (updated)" in out


def test_drift_caps_diff_output_and_reports_how_many_were_dropped(libhelmdocscheck, vp, tmp_path, monkeypatch, capsys):
    chart_dir = make_chart_dir(tmp_path, readme="\n".join(f"line{i}" for i in range(100)) + "\n")
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/helm-docs")
    regenerated = "\n".join(f"other{i}" for i in range(100)) + "\n"
    monkeypatch.setattr(libhelmdocscheck, "run", lambda cmd, **kw: helm_docs_result(regenerated))

    ok, detail = vp.check_helm_docs(chart_dir)
    assert ok is False
    out = capsys.readouterr().out
    diff_lines_printed = [line for line in out.splitlines() if line.startswith("  ") and line[2:3] in ("+", "-")]
    assert len(diff_lines_printed) <= libhelmdocscheck.MAX_DIFF_LINES
    assert "more diff line(s) not shown" in out


def test_run_fix_podiumd_readme_hint_shown_on_drift(libhelmdocscheck, vp, tmp_path, monkeypatch, capsys):
    chart_dir = make_chart_dir(tmp_path)
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/helm-docs")
    regenerated = README_CONTENT + "| newkey | string | `\"x\"` |  |\n"
    monkeypatch.setattr(libhelmdocscheck, "run", lambda cmd, **kw: helm_docs_result(regenerated))

    vp.check_helm_docs(chart_dir)

    out = capsys.readouterr().out
    assert "Run fix-podiumd-readme to regenerate." in out
    assert "never auto-fixed here" not in out
    assert "/helm-docs-check" not in out


def test_never_writes_to_the_real_readme(libhelmdocscheck, vp, tmp_path, monkeypatch):
    """Regardless of drift or not, the real README.md on disk must be
    byte-for-byte untouched — this check is report-only."""
    chart_dir = make_chart_dir(tmp_path)
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/helm-docs")
    monkeypatch.setattr(libhelmdocscheck, "run",
                         lambda cmd, **kw: helm_docs_result(README_CONTENT + "totally different\n"))

    vp.check_helm_docs(chart_dir)

    assert (chart_dir / "README.md").read_text(encoding="utf-8") == README_CONTENT


def test_command_uses_dry_run_and_chart_search_root(libhelmdocscheck, vp, tmp_path, monkeypatch):
    chart_dir = make_chart_dir(tmp_path)
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/helm-docs")
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        return helm_docs_result(README_CONTENT)

    monkeypatch.setattr(libhelmdocscheck, "run", fake_run)
    vp.check_helm_docs(chart_dir)

    assert captured["cmd"][:3] == ["helm-docs", "--dry-run", "--chart-search-root"]
    assert str(chart_dir) in captured["cmd"]
    assert "--template-files" not in captured["cmd"]  # no README.md.gotmpl present


def test_command_includes_template_files_when_gotmpl_present(libhelmdocscheck, vp, tmp_path, monkeypatch):
    chart_dir = make_chart_dir(tmp_path, gotmpl="{{ template \"chart.valuesSection\" . }}\n")
    monkeypatch.setattr(vp.shutil, "which", lambda name: "/usr/bin/helm-docs")
    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = cmd
        return helm_docs_result(README_CONTENT)

    monkeypatch.setattr(libhelmdocscheck, "run", fake_run)
    vp.check_helm_docs(chart_dir)

    assert "--template-files" in captured["cmd"]
    idx = captured["cmd"].index("--template-files")
    assert captured["cmd"][idx + 1] == "README.md.gotmpl"
