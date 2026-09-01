"""main() integration against a real, hermetic temp git repo, plus the
find_repo_root wrapper. find_dependency/get_path/find_app_versions and
component_state_at_ref (which wires them together with git_show_yaml)
are lib.chart's own (see tests/lib/test_chart.py) — baseline_ref_
candidates/resolve_git_ref are lib.gitutil's own (see
tests/lib/test_gitutil.py) — this script only calls through
resolve_baseline_ref/component_state_at_ref, exercised here via main().

No <baseline> CLI argument anymore — main() always shows state at BOTH
release-baseline.yaml baselines (upgrade_docs, release_table)."""
import subprocess

import pytest
import yaml


def git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path):
    git("init", "-q", cwd=tmp_path)
    git("config", "user.email", "test@example.com", cwd=tmp_path)
    git("config", "user.name", "Test", cwd=tmp_path)
    chart_dir = tmp_path / "charts" / "podiumd"
    chart_dir.mkdir(parents=True)
    (chart_dir / "Chart.yaml").write_text(yaml.safe_dump({
        "dependencies": [
            {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297", "repository": "@zac"},
        ]
    }))
    (chart_dir / "values.yaml").write_text(yaml.safe_dump({
        "zac": {"image": {"tag": "5.0.2@sha256:abc"}}
    }))
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "baseline", cwd=tmp_path)
    git("tag", "podiumd-4.8.5", cwd=tmp_path)

    (chart_dir / "values.yaml").write_text(yaml.safe_dump({
        "zac": {"image": {"tag": "5.4.3@sha256:def"}}
    }))
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "bump zac", cwd=tmp_path)
    return tmp_path


def write_baselines(repo, upgrade_docs=None, release_table=None):
    lines = []
    if upgrade_docs is not None:
        lines.append(f'upgrade_docs: "{upgrade_docs}"\n')
    if release_table is not None:
        lines.append(f'release_table: "{release_table}"\n')
    (repo / "charts" / "podiumd" / "release-baseline.yaml").write_text("".join(lines), encoding="utf-8")


def test_find_repo_root_returns_repo_root(scbv, repo, monkeypatch):
    monkeypatch.setattr(scbv, "__file__", str(repo / "charts" / "podiumd" / "scripts" / "fake.py"))
    (repo / "charts" / "podiumd" / "scripts").mkdir(exist_ok=True)
    assert scbv.find_repo_root().resolve() == repo.resolve()


# --- main() integration ---
# main() only calls sys.exit() on error paths; on success it just returns,
# so only the failure-path tests wrap the call in pytest.raises(SystemExit).

def set_argv_and_repo(scbv, monkeypatch, repo, component):
    monkeypatch.setattr("sys.argv", ["show-component-baseline-version", component])
    monkeypatch.setattr(scbv, "find_repo_root", lambda: repo)


def test_main_shows_both_baselines(scbv, repo, monkeypatch, capsys):
    write_baselines(repo, upgrade_docs="4.8.5", release_table="4.8.5")
    set_argv_and_repo(scbv, monkeypatch, repo, "zac")
    scbv.main()  # success path: must not raise
    out = capsys.readouterr().out
    assert "=== upgrade_docs baseline ===" in out
    assert "=== release_table baseline ===" in out
    assert out.count("Helm chart version: 1.0.297") == 2
    assert out.count("5.0.2@sha256:abc") == 2
    assert "5.4.3" not in out  # must read the BASELINE tag's content, not HEAD


def test_main_missing_release_table_key_is_noted_not_an_error(scbv, repo, monkeypatch, capsys):
    write_baselines(repo, upgrade_docs="4.8.5")
    set_argv_and_repo(scbv, monkeypatch, repo, "zac")
    scbv.main()  # upgrade_docs alone is enough to succeed overall
    out = capsys.readouterr().out
    assert "=== upgrade_docs baseline ===" in out
    assert "Helm chart version: 1.0.297" in out
    assert "release-baseline.yaml has no release_table key — skipping" in out


def test_main_unresolvable_baseline_noted_other_still_shown(scbv, repo, monkeypatch, capsys):
    write_baselines(repo, upgrade_docs="9.9.9", release_table="4.8.5")
    set_argv_and_repo(scbv, monkeypatch, repo, "zac")
    scbv.main()  # release_table alone is enough to succeed overall
    out = capsys.readouterr().out
    assert "could not resolve baseline" in out
    assert "Helm chart version: 1.0.297" in out


def test_main_neither_baseline_shown_fails(scbv, repo, monkeypatch, capsys):
    set_argv_and_repo(scbv, monkeypatch, repo, "zac")
    with pytest.raises(SystemExit) as exc_info:
        scbv.main()
    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "release-baseline.yaml has no upgrade_docs key" in out
    assert "release-baseline.yaml has no release_table key" in out


def test_main_unknown_component_fails(scbv, repo, monkeypatch, capsys):
    write_baselines(repo, upgrade_docs="4.8.5", release_table="4.8.5")
    set_argv_and_repo(scbv, monkeypatch, repo, "totally-unknown")
    with pytest.raises(SystemExit) as exc_info:
        scbv.main()
    assert exc_info.value.code == 1
    assert "no dependency named or aliased" in capsys.readouterr().out


def test_main_requires_exactly_one_argument(scbv, monkeypatch):
    monkeypatch.setattr("sys.argv", ["show-component-baseline-version"])
    with pytest.raises(SystemExit) as exc_info:
        scbv.main()
    assert exc_info.value.code == 1


def test_main_too_many_arguments_fails(scbv, monkeypatch):
    monkeypatch.setattr("sys.argv", ["show-component-baseline-version", "zac", "extra"])
    with pytest.raises(SystemExit) as exc_info:
        scbv.main()
    assert exc_info.value.code == 1


@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_main_help_flag_prints_usage_and_exits_zero(scbv, monkeypatch, capsys, flag):
    monkeypatch.setattr("sys.argv", ["show-component-baseline-version", flag])
    with pytest.raises(SystemExit) as exc_info:
        scbv.main()
    assert exc_info.value.code == 0
    assert capsys.readouterr().out == scbv.__doc__ + "\n"
