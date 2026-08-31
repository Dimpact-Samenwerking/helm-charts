"""main() integration against a real, hermetic temp git repo, plus the
find_repo_root wrapper — the same shape as show-component-baseline-
version's own tests (both scripts resolve via the same
lib.chart.component_state_at_ref; see tests/lib/test_chart.py for that
function's own coverage)."""
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


def test_find_repo_root_returns_repo_root(sibv, repo, monkeypatch):
    monkeypatch.setattr(sibv, "__file__", str(repo / "charts" / "podiumd" / "scripts" / "fake.py"))
    (repo / "charts" / "podiumd" / "scripts").mkdir(exist_ok=True)
    assert sibv.find_repo_root().resolve() == repo.resolve()


# --- main() integration ---
# main() only calls sys.exit() on error paths; on success it just returns,
# so only the failure-path tests wrap the call in pytest.raises(SystemExit).

def set_argv_and_repo(sibv, monkeypatch, repo, argv):
    monkeypatch.setattr("sys.argv", ["show-image-baseline-version", *argv])
    monkeypatch.setattr(sibv, "find_repo_root", lambda: repo)


def test_main_shows_app_version_at_baseline(sibv, repo, monkeypatch, capsys):
    set_argv_and_repo(sibv, monkeypatch, repo, ["4.8.5", "zac"])
    sibv.main()  # success path: must not raise
    out = capsys.readouterr().out
    assert "Component: zac (Chart.yaml dependency: zaakafhandelcomponent, values key: zac)" in out
    assert "5.0.2" in out
    assert "5.4.3" not in out  # must read the BASELINE tag's content, not HEAD
    assert "Helm chart version" not in out  # the one thing it deliberately omits


def test_main_no_tag_override_reports_chart_default(sibv, repo, monkeypatch, capsys):
    """A component relying entirely on its chart's own image default (no
    values.yaml override) still resolves — just nothing to report."""
    (repo / "charts" / "podiumd" / "Chart.yaml").write_text(yaml.safe_dump({
        "dependencies": [
            {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297", "repository": "@zac"},
        ]
    }))
    (repo / "charts" / "podiumd" / "values.yaml").write_text(yaml.safe_dump({"zac": {}}))
    git("add", "-A", cwd=repo)
    git("commit", "-q", "-m", "no override", cwd=repo)
    git("tag", "-f", "podiumd-4.8.5", cwd=repo)

    set_argv_and_repo(sibv, monkeypatch, repo, ["4.8.5", "zac"])
    sibv.main()

    out = capsys.readouterr().out
    assert "no tag override found at image under 'zac:' — chart default applies" in out


def test_main_unresolvable_baseline_fails(sibv, repo, monkeypatch, capsys):
    set_argv_and_repo(sibv, monkeypatch, repo, ["9.9.9", "zac"])
    with pytest.raises(SystemExit) as exc_info:
        sibv.main()
    assert exc_info.value.code == 1
    assert "could not resolve baseline" in capsys.readouterr().out


def test_main_unknown_component_fails(sibv, repo, monkeypatch, capsys):
    set_argv_and_repo(sibv, monkeypatch, repo, ["4.8.5", "totally-unknown"])
    with pytest.raises(SystemExit) as exc_info:
        sibv.main()
    assert exc_info.value.code == 1
    assert "no dependency named or aliased" in capsys.readouterr().out


def test_main_uses_release_baseline_when_omitted(sibv, repo, monkeypatch, capsys):
    (repo / "charts" / "podiumd" / "release-baseline").write_text("4.8.5\n", encoding="utf-8")
    set_argv_and_repo(sibv, monkeypatch, repo, ["zac"])
    sibv.main()  # success path: must not raise
    out = capsys.readouterr().out
    assert "No <baseline> given — using release-baseline's '4.8.5'" in out
    assert "Baseline: 4.8.5 (resolved to podiumd-4.8.5)" in out
    assert "5.0.2" in out


def test_main_no_baseline_given_and_no_release_baseline_file_fails(sibv, repo, monkeypatch, capsys):
    set_argv_and_repo(sibv, monkeypatch, repo, ["zac"])
    with pytest.raises(SystemExit) as exc_info:
        sibv.main()
    assert exc_info.value.code == 1
    assert "no <baseline> given and release-baseline doesn't exist" in capsys.readouterr().out


def test_main_requires_at_least_one_argument(sibv, monkeypatch):
    monkeypatch.setattr("sys.argv", ["show-image-baseline-version"])
    with pytest.raises(SystemExit) as exc_info:
        sibv.main()
    assert exc_info.value.code == 1


def test_main_too_many_arguments_fails(sibv, monkeypatch):
    monkeypatch.setattr("sys.argv", ["show-image-baseline-version", "4.8.5", "zac", "extra"])
    with pytest.raises(SystemExit) as exc_info:
        sibv.main()
    assert exc_info.value.code == 1


@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_main_help_flag_prints_usage_and_exits_zero(sibv, monkeypatch, capsys, flag):
    monkeypatch.setattr("sys.argv", ["show-image-baseline-version", flag])
    with pytest.raises(SystemExit) as exc_info:
        sibv.main()
    assert exc_info.value.code == 0
    assert capsys.readouterr().out == sibv.__doc__ + "\n"
