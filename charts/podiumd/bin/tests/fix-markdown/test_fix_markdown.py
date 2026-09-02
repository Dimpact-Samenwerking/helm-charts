"""run_fix/dry_run_fix (pure logic, `run` mocked to avoid needing the real
pymarkdown binary) plus a main() integration test against real files in
tmp_path."""
from types import SimpleNamespace

import pytest

FIXABLE = "# Title\n\ntrailing whitespace   \n"
FIXED = "# Title\n\ntrailing whitespace\n"
CLEAN = "# Title\n\nnothing to fix\n"


def strip_trailing_whitespace_run(cmd, **kwargs):
    """Stand-in for a real `pymarkdown fix` invocation: strips trailing
    whitespace from every line of each path in cmd (mimicking MD009) and
    reports "Fixed: <path>" for any that actually changed — close enough
    to the real tool's own behavior/output shape to exercise this
    script's own parsing/reporting logic without needing pymarkdown
    installed."""
    fixed_lines = []
    paths = cmd[cmd.index("fix") + 1:]
    for path_str in paths:
        original = open(path_str, encoding="utf-8").read()
        new = "\n".join(line.rstrip() for line in original.split("\n"))
        if new != original:
            open(path_str, "w", encoding="utf-8").write(new)
            fixed_lines.append(f"Fixed: {path_str}")
    return SimpleNamespace(returncode=0, stdout="\n".join(fixed_lines), stderr="")


def make_chart(tmp_path, files):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "Chart.yaml").write_text("name: podiumd\nversion: 4.9.0\n", encoding="utf-8")
    for rel_path, content in files.items():
        p = tmp_path / rel_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return tmp_path


# --- run_fix ---

def test_run_fix_returns_paths_pymarkdown_reported_as_fixed(sub, tmp_path, monkeypatch):
    chart_dir = make_chart(tmp_path, {"docs/a.md": FIXABLE, "docs/b.md": CLEAN})
    monkeypatch.setattr(sub, "run", strip_trailing_whitespace_run)

    fixed = sub.run_fix("pymarkdown", [chart_dir / "docs" / "a.md", chart_dir / "docs" / "b.md"])

    assert fixed == [chart_dir / "docs" / "a.md"]
    assert (chart_dir / "docs" / "a.md").read_text(encoding="utf-8") == FIXED
    assert (chart_dir / "docs" / "b.md").read_text(encoding="utf-8") == CLEAN


def test_run_fix_disables_md013_md014_and_md031(sub, tmp_path, monkeypatch):
    chart_dir = make_chart(tmp_path, {"docs/a.md": CLEAN})
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(sub, "run", fake_run)
    sub.run_fix("pymarkdown", [chart_dir / "docs" / "a.md"])

    assert captured["cmd"][:4] == ["pymarkdown", "-d", "md013,md014,md031", "fix"]


# --- dry_run_fix ---

def test_dry_run_fix_reports_changed_files_without_touching_the_real_ones(sub, tmp_path, monkeypatch):
    chart_dir = make_chart(tmp_path, {"docs/a.md": FIXABLE, "docs/b.md": CLEAN})
    monkeypatch.setattr(sub, "run", strip_trailing_whitespace_run)

    files = [chart_dir / "docs" / "a.md", chart_dir / "docs" / "b.md"]
    changed = sub.dry_run_fix("pymarkdown", files, chart_dir)

    assert changed == [chart_dir.joinpath("docs", "a.md").relative_to(chart_dir)]
    # real files completely untouched
    assert (chart_dir / "docs" / "a.md").read_text(encoding="utf-8") == FIXABLE
    assert (chart_dir / "docs" / "b.md").read_text(encoding="utf-8") == CLEAN


def test_dry_run_fix_reports_nothing_when_nothing_would_change(sub, tmp_path, monkeypatch):
    chart_dir = make_chart(tmp_path, {"docs/a.md": CLEAN})
    monkeypatch.setattr(sub, "run", strip_trailing_whitespace_run)

    changed = sub.dry_run_fix("pymarkdown", [chart_dir / "docs" / "a.md"], chart_dir)

    assert changed == []


# --- main() integration ---

@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_main_help_flag_prints_usage_and_exits_zero(sub, tmp_path, monkeypatch, capsys, flag):
    chart_dir = make_chart(tmp_path, {"docs/a.md": FIXABLE})
    monkeypatch.setattr(sub, "CHART_DIR", chart_dir)
    monkeypatch.setattr("sys.argv", ["fix-markdown", flag])

    with pytest.raises(SystemExit) as exc_info:
        sub.main()
    assert exc_info.value.code == 0
    assert capsys.readouterr().out == sub.__doc__ + "\n"
    assert (chart_dir / "docs" / "a.md").read_text(encoding="utf-8") == FIXABLE


def test_main_pymarkdown_not_installed_fails(sub, tmp_path, monkeypatch):
    chart_dir = make_chart(tmp_path, {"docs/a.md": FIXABLE})
    monkeypatch.setattr(sub, "CHART_DIR", chart_dir)
    monkeypatch.setattr(sub, "find_pymarkdown", lambda chart_dir: None)
    monkeypatch.setattr("sys.argv", ["fix-markdown"])

    with pytest.raises(SystemExit) as exc_info:
        sub.main()
    assert exc_info.value.code == 1


def test_main_no_markdown_files_exits_zero(sub, tmp_path, monkeypatch, capsys):
    chart_dir = make_chart(tmp_path, {})
    monkeypatch.setattr(sub, "CHART_DIR", chart_dir)
    monkeypatch.setattr(sub, "find_pymarkdown", lambda chart_dir: "/usr/local/bin/pymarkdown")
    monkeypatch.setattr("sys.argv", ["fix-markdown"])

    with pytest.raises(SystemExit) as exc_info:
        sub.main()
    assert exc_info.value.code == 0
    assert "OK: no markdown files found" in capsys.readouterr().out


def test_main_fixes_a_real_file_and_exits_zero(sub, tmp_path, monkeypatch, capsys):
    chart_dir = make_chart(tmp_path, {"docs/a.md": FIXABLE})
    monkeypatch.setattr(sub, "CHART_DIR", chart_dir)
    monkeypatch.setattr(sub, "find_pymarkdown", lambda chart_dir: "/usr/local/bin/pymarkdown")
    monkeypatch.setattr(sub, "run", strip_trailing_whitespace_run)
    monkeypatch.setattr("sys.argv", ["fix-markdown"])

    with pytest.raises(SystemExit) as exc_info:
        sub.main()
    assert exc_info.value.code == 0
    assert (chart_dir / "docs" / "a.md").read_text(encoding="utf-8") == FIXED
    out = capsys.readouterr().out
    assert "Fixed 1 file(s):" in out
    assert "docs/a.md" in out
    assert "human judgment" in out


def test_main_nothing_to_fix_exits_zero(sub, tmp_path, monkeypatch, capsys):
    chart_dir = make_chart(tmp_path, {"docs/a.md": CLEAN})
    monkeypatch.setattr(sub, "CHART_DIR", chart_dir)
    monkeypatch.setattr(sub, "find_pymarkdown", lambda chart_dir: "/usr/local/bin/pymarkdown")
    monkeypatch.setattr(sub, "run", strip_trailing_whitespace_run)
    monkeypatch.setattr("sys.argv", ["fix-markdown"])

    with pytest.raises(SystemExit) as exc_info:
        sub.main()
    assert exc_info.value.code == 0
    assert "OK: nothing pymarkdown fix could resolve" in capsys.readouterr().out


def test_main_dry_run_reports_but_does_not_write(sub, tmp_path, monkeypatch, capsys):
    chart_dir = make_chart(tmp_path, {"docs/a.md": FIXABLE})
    monkeypatch.setattr(sub, "CHART_DIR", chart_dir)
    monkeypatch.setattr(sub, "find_pymarkdown", lambda chart_dir: "/usr/local/bin/pymarkdown")
    monkeypatch.setattr(sub, "run", strip_trailing_whitespace_run)
    monkeypatch.setattr("sys.argv", ["fix-markdown", "--dry-run"])

    with pytest.raises(SystemExit) as exc_info:
        sub.main()
    assert exc_info.value.code == 1
    assert (chart_dir / "docs" / "a.md").read_text(encoding="utf-8") == FIXABLE
    out = capsys.readouterr().out
    assert "1 file(s) would be fixed" in out
    assert "docs/a.md" in out
    assert "dry-run" in out


def test_main_dry_run_nothing_to_fix_exits_zero(sub, tmp_path, monkeypatch, capsys):
    chart_dir = make_chart(tmp_path, {"docs/a.md": CLEAN})
    monkeypatch.setattr(sub, "CHART_DIR", chart_dir)
    monkeypatch.setattr(sub, "find_pymarkdown", lambda chart_dir: "/usr/local/bin/pymarkdown")
    monkeypatch.setattr(sub, "run", strip_trailing_whitespace_run)
    monkeypatch.setattr("sys.argv", ["fix-markdown", "--dry-run"])

    with pytest.raises(SystemExit) as exc_info:
        sub.main()
    assert exc_info.value.code == 0
