"""create-podiumd-version.py: bumps Chart.yaml's version/appVersion to the
target named by the current branch, then delegates to set-doc-baseline.py
for the outgoing (baseline) version. lib.gitutil.current_branch/
find_repo_root and subprocess.run (the set-doc-baseline.py delegation) are
mocked out via cpv.* directly — no real git repo or subprocess needed."""
import subprocess

import pytest


def write_chart_yaml(path, version, app_version=None):
    app_version = app_version if app_version is not None else version
    path.write_text(
        f'apiVersion: v2\nname: podiumd\ntype: application\n'
        f'version: {version}\nappVersion: "{app_version}"\ndependencies: []\n',
        encoding="utf-8",
    )


# --- current_chart_version / version_tuple ---

def test_current_chart_version_reads_chart_yaml(cpv, tmp_path, monkeypatch):
    chart_yaml = tmp_path / "Chart.yaml"
    write_chart_yaml(chart_yaml, "4.9.0")
    monkeypatch.setattr(cpv, "CHART_YAML", chart_yaml)
    assert cpv.current_chart_version() == "4.9.0"


def test_version_tuple_orders_numerically_not_lexically(cpv):
    assert cpv.version_tuple("4.9.0") < cpv.version_tuple("4.10.0")
    assert cpv.version_tuple("4.9.0") == (4, 9, 0)


# --- update_chart_version ---

def test_update_chart_version_bumps_both_fields(cpv, tmp_path, monkeypatch):
    chart_yaml = tmp_path / "Chart.yaml"
    write_chart_yaml(chart_yaml, "4.9.0")
    monkeypatch.setattr(cpv, "CHART_YAML", chart_yaml)

    changed = cpv.update_chart_version("4.10.0")

    assert changed == ["version", "appVersion"]
    text = chart_yaml.read_text()
    assert "version: 4.10.0\n" in text
    assert 'appVersion: "4.10.0"\n' in text


def test_update_chart_version_preserves_quote_style_and_other_lines(cpv, tmp_path, monkeypatch):
    chart_yaml = tmp_path / "Chart.yaml"
    chart_yaml.write_text(
        'apiVersion: v2\nname: podiumd\nversion: 4.9.0\nappVersion: "4.9.0"\n'
        'dependencies:\n  - name: foo\n    version: 1.2.3\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(cpv, "CHART_YAML", chart_yaml)

    cpv.update_chart_version("4.10.0")

    text = chart_yaml.read_text()
    assert "version: 4.10.0\n" in text  # bare style preserved
    assert 'appVersion: "4.10.0"\n' in text  # quoted style preserved
    assert "    version: 1.2.3\n" in text  # unrelated nested "version:" untouched


def test_update_chart_version_missing_version_line_raises(cpv, tmp_path, monkeypatch):
    chart_yaml = tmp_path / "Chart.yaml"
    chart_yaml.write_text("apiVersion: v2\nname: podiumd\n", encoding="utf-8")
    monkeypatch.setattr(cpv, "CHART_YAML", chart_yaml)

    with pytest.raises(SystemExit):
        cpv.update_chart_version("4.10.0")


# --- main(): argument/help handling ---

def test_help_flag_prints_docstring_and_exits_0(cpv, monkeypatch, capsys):
    monkeypatch.setattr(cpv.sys, "argv", ["create-podiumd-version.py", "--help"])
    with pytest.raises(SystemExit) as exc_info:
        cpv.main()
    assert exc_info.value.code == 0
    assert "Usage:" in capsys.readouterr().out


def test_unexpected_arg_prints_docstring_and_exits_1(cpv, monkeypatch, capsys):
    monkeypatch.setattr(cpv.sys, "argv", ["create-podiumd-version.py", "unexpected"])
    with pytest.raises(SystemExit) as exc_info:
        cpv.main()
    assert exc_info.value.code == 1
    assert "Usage:" in capsys.readouterr().out


# --- main(): precondition failures ---

def test_not_a_git_repo_fails(cpv, monkeypatch, capsys):
    monkeypatch.setattr(cpv.sys, "argv", ["create-podiumd-version.py"])
    monkeypatch.setattr(cpv, "find_repo_root", lambda chart_dir: None)

    with pytest.raises(SystemExit) as exc_info:
        cpv.main()

    assert exc_info.value.code == 1
    assert "not inside a git repository" in capsys.readouterr().out


def test_wrong_branch_name_fails(cpv, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cpv.sys, "argv", ["create-podiumd-version.py"])
    monkeypatch.setattr(cpv, "find_repo_root", lambda chart_dir: tmp_path)
    monkeypatch.setattr(cpv, "current_branch", lambda repo_root: "feature/podiumd-4.10.0-something")

    with pytest.raises(SystemExit) as exc_info:
        cpv.main()

    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "does not match" in out
    assert "feature/podiumd-4.10.0-something" in out


def test_detached_head_fails_with_readable_message(cpv, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cpv.sys, "argv", ["create-podiumd-version.py"])
    monkeypatch.setattr(cpv, "find_repo_root", lambda chart_dir: tmp_path)
    monkeypatch.setattr(cpv, "current_branch", lambda repo_root: "")

    with pytest.raises(SystemExit) as exc_info:
        cpv.main()

    assert exc_info.value.code == 1
    assert "detached HEAD" in capsys.readouterr().out


def test_baseline_not_older_than_target_fails(cpv, tmp_path, monkeypatch, capsys):
    chart_yaml = tmp_path / "Chart.yaml"
    write_chart_yaml(chart_yaml, "4.10.0")
    monkeypatch.setattr(cpv, "CHART_YAML", chart_yaml)
    monkeypatch.setattr(cpv.sys, "argv", ["create-podiumd-version.py"])
    monkeypatch.setattr(cpv, "find_repo_root", lambda chart_dir: tmp_path)
    monkeypatch.setattr(cpv, "current_branch", lambda repo_root: "feature/podiumd-4.9.0")

    with pytest.raises(SystemExit) as exc_info:
        cpv.main()

    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "not older than" in out


def test_baseline_equal_to_target_fails(cpv, tmp_path, monkeypatch, capsys):
    chart_yaml = tmp_path / "Chart.yaml"
    write_chart_yaml(chart_yaml, "4.9.0")
    monkeypatch.setattr(cpv, "CHART_YAML", chart_yaml)
    monkeypatch.setattr(cpv.sys, "argv", ["create-podiumd-version.py"])
    monkeypatch.setattr(cpv, "find_repo_root", lambda chart_dir: tmp_path)
    monkeypatch.setattr(cpv, "current_branch", lambda repo_root: "feature/podiumd-4.9.0")

    with pytest.raises(SystemExit) as exc_info:
        cpv.main()

    assert exc_info.value.code == 1


# --- main(): success path ---

def test_success_bumps_chart_and_delegates_to_set_doc_baseline(cpv, tmp_path, monkeypatch, capsys):
    """Numeric comparison must beat lexical: 4.9.0 -> 4.10.0 would look
    like a *downgrade* under plain string comparison ("4.9.0" > "4.10.0"
    lexically), so this case doubles as the regression test for that."""
    chart_yaml = tmp_path / "Chart.yaml"
    write_chart_yaml(chart_yaml, "4.9.0")
    monkeypatch.setattr(cpv, "CHART_YAML", chart_yaml)
    monkeypatch.setattr(cpv.sys, "argv", ["create-podiumd-version.py"])
    monkeypatch.setattr(cpv, "find_repo_root", lambda chart_dir: tmp_path)
    monkeypatch.setattr(cpv, "current_branch", lambda repo_root: "feature/podiumd-4.10.0")

    calls = []

    def fake_run(cmd, *args, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(cpv.subprocess, "run", fake_run)

    with pytest.raises(SystemExit) as exc_info:
        cpv.main()

    assert exc_info.value.code == 0
    assert chart_yaml.read_text().splitlines()[3] == "version: 4.10.0"
    assert len(calls) == 1
    assert calls[0][0] == cpv.sys.executable
    assert calls[0][1] == str(cpv.SET_DOC_BASELINE_SCRIPT)
    assert calls[0][2] == "4.9.0"
    out = capsys.readouterr().out
    assert "4.9.0 -> 4.10.0" in out
    assert "set-doc-baseline.py 4.9.0" in out


def test_success_propagates_set_doc_baseline_failure_exit_code(cpv, tmp_path, monkeypatch):
    chart_yaml = tmp_path / "Chart.yaml"
    write_chart_yaml(chart_yaml, "4.9.0")
    monkeypatch.setattr(cpv, "CHART_YAML", chart_yaml)
    monkeypatch.setattr(cpv.sys, "argv", ["create-podiumd-version.py"])
    monkeypatch.setattr(cpv, "find_repo_root", lambda chart_dir: tmp_path)
    monkeypatch.setattr(cpv, "current_branch", lambda repo_root: "feature/podiumd-4.10.0")
    monkeypatch.setattr(cpv.subprocess, "run", lambda cmd, *a, **k: subprocess.CompletedProcess(cmd, 1))

    with pytest.raises(SystemExit) as exc_info:
        cpv.main()

    assert exc_info.value.code == 1
