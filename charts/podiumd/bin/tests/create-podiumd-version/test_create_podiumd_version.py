"""create-podiumd-version: bumps Chart.yaml's version/appVersion to the
target named by the current branch, then delegates to create-doc-version
for the outgoing (baseline) version. Also writes both baselines to
release-baseline.yaml (lib.chart.write_release_baselines) -- upgrade_docs
always, release_table only on a minor bump -- see bump_kind for the
single-increment validation this all hinges on.

lib.gitutil.current_branch and lib.procutil.run_script (the
create-doc-version delegation) are mocked out via cpv.* directly.
find_repo_root, however, is only mocked to point at a real, hermetic
temp git repo (the `repo` fixture) rather than faked outright -- main()
now resolves both baselines to actual git refs via resolve_baseline_ref
before it writes anything, and a bare tmp_path isn't a git repo at all,
so that resolution needs something real to succeed against."""
import subprocess

import pytest


def git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path):
    """A hermetic git repo tagged podiumd-4.8.5 and podiumd-4.9.0 -- the
    two baselines success-path tests below bump away from/reference."""
    git("init", "-q", cwd=tmp_path)
    git("config", "user.email", "test@example.com", cwd=tmp_path)
    git("config", "user.name", "Test", cwd=tmp_path)
    (tmp_path / "README.md").write_text("x\n", encoding="utf-8")
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "baseline 4.8.5", cwd=tmp_path)
    git("tag", "podiumd-4.8.5", cwd=tmp_path)
    (tmp_path / "README.md").write_text("y\n", encoding="utf-8")
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "baseline 4.9.0", cwd=tmp_path)
    git("tag", "podiumd-4.9.0", cwd=tmp_path)
    return tmp_path


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


# --- bump_kind ---

def test_bump_kind_single_patch_increment(cpv):
    assert cpv.bump_kind("4.9.0", "4.9.1") == "patch"


def test_bump_kind_single_minor_increment(cpv):
    assert cpv.bump_kind("4.9.0", "4.10.0") == "minor"


def test_bump_kind_minor_increment_requires_patch_reset_to_zero(cpv):
    assert cpv.bump_kind("4.9.5", "4.10.1") is None


def test_bump_kind_skipped_patch_version_rejected(cpv):
    assert cpv.bump_kind("4.9.0", "4.9.2") is None


def test_bump_kind_skipped_minor_version_rejected(cpv):
    assert cpv.bump_kind("4.9.0", "4.11.0") is None


def test_bump_kind_major_version_change_rejected(cpv):
    """Out of scope for this tool entirely -- not a third case to branch
    on, just another invalid jump."""
    assert cpv.bump_kind("4.9.0", "5.0.0") is None


def test_bump_kind_same_version_rejected(cpv):
    assert cpv.bump_kind("4.9.0", "4.9.0") is None


def test_bump_kind_lower_target_rejected(cpv):
    assert cpv.bump_kind("4.10.0", "4.9.0") is None


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
    monkeypatch.setattr(cpv.sys, "argv", ["create-podiumd-version", "--help"])
    with pytest.raises(SystemExit) as exc_info:
        cpv.main()
    assert exc_info.value.code == 0
    assert "Usage:" in capsys.readouterr().out


def test_unexpected_arg_prints_docstring_and_exits_1(cpv, monkeypatch, capsys):
    monkeypatch.setattr(cpv.sys, "argv", ["create-podiumd-version", "unexpected"])
    with pytest.raises(SystemExit) as exc_info:
        cpv.main()
    assert exc_info.value.code == 1
    assert "Usage:" in capsys.readouterr().out


# --- main(): precondition failures ---

def test_not_a_git_repo_fails(cpv, monkeypatch, capsys):
    monkeypatch.setattr(cpv.sys, "argv", ["create-podiumd-version"])
    monkeypatch.setattr(cpv, "find_repo_root", lambda chart_dir: None)

    with pytest.raises(SystemExit) as exc_info:
        cpv.main()

    assert exc_info.value.code == 1
    assert "not inside a git repository" in capsys.readouterr().out


def test_wrong_branch_name_fails(cpv, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cpv.sys, "argv", ["create-podiumd-version"])
    monkeypatch.setattr(cpv, "find_repo_root", lambda chart_dir: tmp_path)
    monkeypatch.setattr(cpv, "current_branch", lambda repo_root: "feature/podiumd-4.10.0-something")

    with pytest.raises(SystemExit) as exc_info:
        cpv.main()

    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "does not match" in out
    assert "feature/podiumd-4.10.0-something" in out


def test_detached_head_fails_with_readable_message(cpv, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cpv.sys, "argv", ["create-podiumd-version"])
    monkeypatch.setattr(cpv, "find_repo_root", lambda chart_dir: tmp_path)
    monkeypatch.setattr(cpv, "current_branch", lambda repo_root: "")

    with pytest.raises(SystemExit) as exc_info:
        cpv.main()

    assert exc_info.value.code == 1
    assert "detached HEAD" in capsys.readouterr().out


def test_baseline_not_older_than_target_fails(cpv, tmp_path, monkeypatch, capsys):
    """4.10.0 -> 4.9.0 isn't a valid single-increment jump either way --
    same bump_kind()-based refusal as a skipped or major version."""
    chart_yaml = tmp_path / "Chart.yaml"
    write_chart_yaml(chart_yaml, "4.10.0")
    monkeypatch.setattr(cpv, "CHART_YAML", chart_yaml)
    monkeypatch.setattr(cpv.sys, "argv", ["create-podiumd-version"])
    monkeypatch.setattr(cpv, "find_repo_root", lambda chart_dir: tmp_path)
    monkeypatch.setattr(cpv, "current_branch", lambda repo_root: "feature/podiumd-4.9.0")

    with pytest.raises(SystemExit) as exc_info:
        cpv.main()

    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "not a single patch increment" in out
    assert "not a single minor increment" not in out  # exact phrasing is "or a single minor..."


def test_baseline_equal_to_target_fails(cpv, tmp_path, monkeypatch, capsys):
    chart_yaml = tmp_path / "Chart.yaml"
    write_chart_yaml(chart_yaml, "4.9.0")
    monkeypatch.setattr(cpv, "CHART_YAML", chart_yaml)
    monkeypatch.setattr(cpv.sys, "argv", ["create-podiumd-version"])
    monkeypatch.setattr(cpv, "find_repo_root", lambda chart_dir: tmp_path)
    monkeypatch.setattr(cpv, "current_branch", lambda repo_root: "feature/podiumd-4.9.0")

    with pytest.raises(SystemExit) as exc_info:
        cpv.main()

    assert exc_info.value.code == 1


def test_major_version_bump_refused(cpv, tmp_path, monkeypatch, capsys):
    chart_yaml = tmp_path / "Chart.yaml"
    write_chart_yaml(chart_yaml, "4.9.0")
    monkeypatch.setattr(cpv, "CHART_YAML", chart_yaml)
    monkeypatch.setattr(cpv.sys, "argv", ["create-podiumd-version"])
    monkeypatch.setattr(cpv, "find_repo_root", lambda chart_dir: tmp_path)
    monkeypatch.setattr(cpv, "current_branch", lambda repo_root: "feature/podiumd-5.0.0")

    with pytest.raises(SystemExit) as exc_info:
        cpv.main()

    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "major-version change is out of scope" in out
    assert chart_yaml.read_text().splitlines()[3] == "version: 4.9.0"  # untouched


def test_patch_bump_without_a_recorded_release_table_baseline_refused(cpv, repo, monkeypatch, capsys):
    """No release-baseline.yaml at all yet -- a patch bump has nothing to
    leave release_table unchanged AT, so it must refuse rather than
    silently proceed with no release_table recorded."""
    chart_yaml = repo / "Chart.yaml"
    write_chart_yaml(chart_yaml, "4.9.0")
    monkeypatch.setattr(cpv, "CHART_YAML", chart_yaml)
    monkeypatch.setattr(cpv, "CHART_DIR", repo)
    monkeypatch.setattr(cpv.sys, "argv", ["create-podiumd-version"])
    monkeypatch.setattr(cpv, "find_repo_root", lambda chart_dir: repo)
    monkeypatch.setattr(cpv, "current_branch", lambda repo_root: "feature/podiumd-4.9.1")

    with pytest.raises(SystemExit) as exc_info:
        cpv.main()

    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "release_table baseline is not yet recorded" in out
    assert not (repo / "release-baseline.yaml").is_file()
    assert chart_yaml.read_text().splitlines()[3] == "version: 4.9.0"  # untouched


def test_patch_bump_with_unresolvable_existing_release_table_refused(cpv, repo, monkeypatch, capsys):
    chart_yaml = repo / "Chart.yaml"
    write_chart_yaml(chart_yaml, "4.9.0")
    (repo / "release-baseline.yaml").write_text('release_table: "9.9.9"\n', encoding="utf-8")
    monkeypatch.setattr(cpv, "CHART_YAML", chart_yaml)
    monkeypatch.setattr(cpv, "CHART_DIR", repo)
    monkeypatch.setattr(cpv.sys, "argv", ["create-podiumd-version"])
    monkeypatch.setattr(cpv, "find_repo_root", lambda chart_dir: repo)
    monkeypatch.setattr(cpv, "current_branch", lambda repo_root: "feature/podiumd-4.9.1")

    with pytest.raises(SystemExit) as exc_info:
        cpv.main()

    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "release_table baseline '9.9.9'" in out
    assert "could not resolve" in out


# --- main(): success path ---

def test_minor_bump_writes_both_baselines_and_delegates(cpv, repo, monkeypatch, capsys):
    """Numeric comparison must beat lexical: 4.9.0 -> 4.10.0 would look
    like a *downgrade* under plain string comparison ("4.9.0" > "4.10.0"
    lexically), so this case doubles as the regression test for that. A
    minor bump writes BOTH upgrade_docs and release_table to the same
    outgoing baseline."""
    chart_yaml = repo / "Chart.yaml"
    write_chart_yaml(chart_yaml, "4.9.0")
    monkeypatch.setattr(cpv, "CHART_YAML", chart_yaml)
    monkeypatch.setattr(cpv, "CHART_DIR", repo)
    monkeypatch.setattr(cpv.sys, "argv", ["create-podiumd-version"])
    monkeypatch.setattr(cpv, "find_repo_root", lambda chart_dir: repo)
    monkeypatch.setattr(cpv, "current_branch", lambda repo_root: "feature/podiumd-4.10.0")

    calls = []

    def fake_run(cmd, *args, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(cpv, "run_script", fake_run)

    with pytest.raises(SystemExit) as exc_info:
        cpv.main()

    assert exc_info.value.code == 0
    assert chart_yaml.read_text().splitlines()[3] == "version: 4.10.0"
    baselines = (repo / "release-baseline.yaml").read_text(encoding="utf-8")
    assert 'upgrade_docs: 4.9.0' in baselines or 'upgrade_docs: "4.9.0"' in baselines
    assert 'release_table: 4.9.0' in baselines or 'release_table: "4.9.0"' in baselines
    assert len(calls) == 1
    assert calls[0][0] == cpv.sys.executable
    assert calls[0][1] == str(cpv.CREATE_DOC_VERSION_SCRIPT)
    assert calls[0][2] == "4.9.0"
    out = capsys.readouterr().out
    assert "4.9.0 -> 4.10.0 (minor bump)" in out
    assert "upgrade_docs 4.9.0 (resolved to podiumd-4.9.0)" in out
    assert "release_table 4.9.0 (resolved to podiumd-4.9.0)" in out
    assert "create-doc-version 4.9.0" in out


def test_patch_bump_writes_only_upgrade_docs_leaves_release_table(cpv, repo, monkeypatch, capsys):
    chart_yaml = repo / "Chart.yaml"
    write_chart_yaml(chart_yaml, "4.9.0")
    (repo / "release-baseline.yaml").write_text('release_table: "4.8.5"\n', encoding="utf-8")
    monkeypatch.setattr(cpv, "CHART_YAML", chart_yaml)
    monkeypatch.setattr(cpv, "CHART_DIR", repo)
    monkeypatch.setattr(cpv.sys, "argv", ["create-podiumd-version"])
    monkeypatch.setattr(cpv, "find_repo_root", lambda chart_dir: repo)
    monkeypatch.setattr(cpv, "current_branch", lambda repo_root: "feature/podiumd-4.9.1")
    monkeypatch.setattr(cpv, "run_script", lambda cmd, *a, **k: subprocess.CompletedProcess(cmd, 0))

    with pytest.raises(SystemExit) as exc_info:
        cpv.main()

    assert exc_info.value.code == 0
    assert chart_yaml.read_text().splitlines()[3] == "version: 4.9.1"
    baselines = (repo / "release-baseline.yaml").read_text(encoding="utf-8")
    assert 'upgrade_docs: 4.9.0' in baselines or 'upgrade_docs: "4.9.0"' in baselines
    assert "4.8.5" in baselines  # release_table untouched
    out = capsys.readouterr().out
    assert "4.9.0 -> 4.9.1 (patch bump)" in out
    assert "upgrade_docs 4.9.0 (resolved to podiumd-4.9.0)" in out
    assert "release_table unchanged (4.8.5, resolved to podiumd-4.8.5)" in out


def test_success_propagates_create_doc_version_failure_exit_code(cpv, repo, monkeypatch):
    chart_yaml = repo / "Chart.yaml"
    write_chart_yaml(chart_yaml, "4.9.0")
    monkeypatch.setattr(cpv, "CHART_YAML", chart_yaml)
    monkeypatch.setattr(cpv, "CHART_DIR", repo)
    monkeypatch.setattr(cpv.sys, "argv", ["create-podiumd-version"])
    monkeypatch.setattr(cpv, "find_repo_root", lambda chart_dir: repo)
    monkeypatch.setattr(cpv, "current_branch", lambda repo_root: "feature/podiumd-4.10.0")
    monkeypatch.setattr(cpv, "run_script", lambda cmd, *a, **k: subprocess.CompletedProcess(cmd, 1))

    with pytest.raises(SystemExit) as exc_info:
        cpv.main()

    assert exc_info.value.code == 1


def test_baseline_unresolvable_fails_without_writing_anything(cpv, repo, monkeypatch, capsys):
    """A baseline that doesn't resolve to a real podiumd-<baseline> tag or
    feature/podiumd-<baseline> branch must refuse before touching
    Chart.yaml or release-baseline.yaml -- same guard change-podiumd-
    baseline enforces on write, reused here via
    lib.gitutil.resolve_baseline_ref."""
    chart_yaml = repo / "Chart.yaml"
    write_chart_yaml(chart_yaml, "9.9.9")  # no podiumd-9.9.9 tag/branch exists
    monkeypatch.setattr(cpv, "CHART_YAML", chart_yaml)
    monkeypatch.setattr(cpv, "CHART_DIR", repo)
    monkeypatch.setattr(cpv.sys, "argv", ["create-podiumd-version"])
    monkeypatch.setattr(cpv, "find_repo_root", lambda chart_dir: repo)
    monkeypatch.setattr(cpv, "current_branch", lambda repo_root: "feature/podiumd-9.9.10")

    with pytest.raises(SystemExit) as exc_info:
        cpv.main()

    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "upgrade_docs baseline '9.9.9'" in out
    assert "could not resolve" in out
    assert chart_yaml.read_text().splitlines()[3] == "version: 9.9.9"  # untouched
    assert not (repo / "release-baseline.yaml").is_file()
