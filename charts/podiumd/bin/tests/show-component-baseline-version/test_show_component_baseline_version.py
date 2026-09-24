"""main() integration against a real, hermetic temp git repo.
find_dependency/get_path/find_app_versions and
component_state_at_baseline (which wires them together with lib.
release_baseline.resolve_baseline_chart_state) are lib.chart's own (see
tests/lib/test_chart.py) — baseline_ref_candidates/resolve_git_ref are
lib.gitutil's own (see tests/lib/test_gitutil.py) — this script only
calls through component_state_at_baseline (via lib.baseline_report.
show_baseline_section), exercised here via main().

No <baseline> CLI argument anymore — main() always shows state at BOTH
release-baseline.yaml baselines (upgrade_docs, release_table)."""

import subprocess

from pathlib import Path
from types import ModuleType

import pytest
import yaml


def git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path: Path):
    git("init", "-q", cwd=tmp_path)
    git("config", "user.email", "test@example.com", cwd=tmp_path)
    git("config", "user.name", "Test", cwd=tmp_path)
    chart_dir = tmp_path / "charts" / "podiumd"
    chart_dir.mkdir(parents=True)
    (chart_dir / "Chart.yaml").write_text(
        yaml.safe_dump(
            {
                "dependencies": [
                    {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297", "repository": "@zac"},
                ]
            }
        )
    )
    (chart_dir / "values.yaml").write_text(yaml.safe_dump({"zac": {"image": {"tag": "5.0.2@sha256:abc"}}}))
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "baseline", cwd=tmp_path)
    git("tag", "podiumd-4.8.5", cwd=tmp_path)

    (chart_dir / "values.yaml").write_text(yaml.safe_dump({"zac": {"image": {"tag": "5.4.3@sha256:def"}}}))
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "bump zac", cwd=tmp_path)
    return tmp_path


def write_baselines(repo, upgrade_docs=None, release_table=None):
    lines = []
    if upgrade_docs is not None:
        lines.append(f'upgrade_docs: "{upgrade_docs}"\n')
    if release_table is not None:
        lines.append(f'release_table: "{release_table}"\n')
    (repo / "charts" / "podiumd" / "etc").mkdir(exist_ok=True)
    (repo / "charts" / "podiumd" / "etc" / "release-baseline.yaml").write_text("".join(lines), encoding="utf-8")


# --- main() integration ---
# main() only calls sys.exit() on error paths; on success it just returns,
# so only the failure-path tests wrap the call in pytest.raises(SystemExit).


def set_argv_and_repo(scbv: ModuleType, monkeypatch: pytest.MonkeyPatch, repo, component):
    monkeypatch.setattr("sys.argv", ["show-component-baseline-version", component])
    monkeypatch.setattr(scbv, "CHART_DIR", repo / "charts" / "podiumd")


def test_main_shows_both_baselines(
    scbv: ModuleType, repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    write_baselines(repo, upgrade_docs="4.8.5", release_table="4.8.5")
    set_argv_and_repo(scbv, monkeypatch, repo, "zac")
    scbv.main()  # success path: must not raise
    out = capsys.readouterr().out
    assert "=== upgrade_docs baseline ===" in out
    assert "=== release_table baseline ===" in out
    assert out.count("Helm chart version: 1.0.297") == 2
    assert out.count("5.0.2@sha256:abc") == 2
    assert "5.4.3" not in out  # must read the BASELINE tag's content, not HEAD


def test_main_missing_release_table_key_is_noted_not_an_error(
    scbv: ModuleType, repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    write_baselines(repo, upgrade_docs="4.8.5")
    set_argv_and_repo(scbv, monkeypatch, repo, "zac")
    scbv.main()  # upgrade_docs alone is enough to succeed overall
    out = capsys.readouterr().out
    assert "=== upgrade_docs baseline ===" in out
    assert "Helm chart version: 1.0.297" in out
    assert "release-baseline.yaml has no release_table key — skipping" in out


def test_main_unresolvable_baseline_noted_other_still_shown(
    scbv: ModuleType, repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    write_baselines(repo, upgrade_docs="9.9.9", release_table="4.8.5")
    set_argv_and_repo(scbv, monkeypatch, repo, "zac")
    scbv.main()  # release_table alone is enough to succeed overall
    out = capsys.readouterr().out
    assert "could not resolve baseline" in out
    assert "Helm chart version: 1.0.297" in out


def test_main_neither_baseline_shown_fails(
    scbv: ModuleType, repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    set_argv_and_repo(scbv, monkeypatch, repo, "zac")
    with pytest.raises(SystemExit) as exc_info:
        scbv.main()
    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "release-baseline.yaml has no upgrade_docs key" in out
    assert "release-baseline.yaml has no release_table key" in out


def test_main_unknown_component_fails(
    scbv: ModuleType, repo, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    write_baselines(repo, upgrade_docs="4.8.5", release_table="4.8.5")
    set_argv_and_repo(scbv, monkeypatch, repo, "totally-unknown")
    with pytest.raises(SystemExit) as exc_info:
        scbv.main()
    assert exc_info.value.code == 1
    assert "no dependency named or aliased" in capsys.readouterr().out


def test_main_requires_exactly_one_argument(scbv: ModuleType, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("sys.argv", ["show-component-baseline-version"])
    with pytest.raises(SystemExit) as exc_info:
        scbv.main()
    assert exc_info.value.code == 1


def test_main_too_many_arguments_fails(scbv: ModuleType, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("sys.argv", ["show-component-baseline-version", "zac", "extra"])
    with pytest.raises(SystemExit) as exc_info:
        scbv.main()
    assert exc_info.value.code == 1


@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_main_help_flag_prints_usage_and_exits_zero(
    scbv: ModuleType, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], flag
):
    monkeypatch.setattr("sys.argv", ["show-component-baseline-version", flag])
    with pytest.raises(SystemExit) as exc_info:
        scbv.main()
    assert exc_info.value.code == 0
    assert capsys.readouterr().out == f"{scbv.__doc__}\n"


def test_main_shows_a_native_component_without_chart_version(
    scbv: ModuleType, repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """frankgateway (a native component, settings.yaml default) has no
    Chart.yaml dependency: its image tag is shown, no chart version."""
    chart_dir = repo / "charts" / "podiumd"
    (chart_dir / "values.yaml").write_text(yaml.safe_dump({"frankgateway": {"image": {"tag": "104@sha256:fff"}}}))
    git("add", "-A", cwd=repo)
    git("commit", "-q", "-m", "add frankgateway", cwd=repo)
    git("tag", "podiumd-4.9.1", cwd=repo)
    write_baselines(repo, upgrade_docs="4.9.1")
    set_argv_and_repo(scbv, monkeypatch, repo, "frankgateway")
    scbv.main()
    out = capsys.readouterr().out
    assert "Component: frankgateway (native, no Chart.yaml dependency; values key: frankgateway)" in out
    assert "image: 104  (104@sha256:fff)" in out
    assert "Helm chart version" not in out
