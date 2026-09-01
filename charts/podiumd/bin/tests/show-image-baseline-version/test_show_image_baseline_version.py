"""main() integration against a real, hermetic temp git repo, plus the
find_repo_root wrapper — <key> <basename> resolved via lib.image_version.
resolve_scoped_matches against values.yaml TEXT as it was at each
release-baseline.yaml baseline (via `git show`), same resolution
update-image-version/verify-image-version's own <key> <basename> use,
just applied to a past ref instead of the current file.

No <baseline> CLI argument anymore — main() always shows state at BOTH
release-baseline.yaml baselines (upgrade_docs, release_table)."""
import subprocess

import pytest


def git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def write_zac_values(chart_dir, version, digest):
    (chart_dir / "values.yaml").write_text(
        "zac:\n"
        "  image:\n"
        "    repository: ghcr.io/infonl/zaakafhandelcomponent\n"
        f'    tag: "{version}@sha256:{digest}"\n',
        encoding="utf-8",
    )


@pytest.fixture
def repo(tmp_path):
    git("init", "-q", cwd=tmp_path)
    git("config", "user.email", "test@example.com", cwd=tmp_path)
    git("config", "user.name", "Test", cwd=tmp_path)
    chart_dir = tmp_path / "charts" / "podiumd"
    chart_dir.mkdir(parents=True)
    write_zac_values(chart_dir, "5.0.2", "a" * 64)
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "baseline", cwd=tmp_path)
    git("tag", "podiumd-4.8.5", cwd=tmp_path)

    (chart_dir / "values.yaml").write_text("zac: {}\n", encoding="utf-8")
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "rely on chart default", cwd=tmp_path)
    git("tag", "podiumd-4.9.0", cwd=tmp_path)

    write_zac_values(chart_dir, "5.4.3", "b" * 64)
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


def test_find_repo_root_returns_repo_root(sibv, repo, monkeypatch):
    monkeypatch.setattr(sibv, "__file__", str(repo / "charts" / "podiumd" / "scripts" / "fake.py"))
    (repo / "charts" / "podiumd" / "scripts").mkdir(exist_ok=True)
    assert sibv.find_repo_root().resolve() == repo.resolve()


# --- main() integration ---
# main() only calls sys.exit() on error paths; on success it just returns,
# so only the failure-path tests wrap the call in pytest.raises(SystemExit).

def set_argv_and_repo(sibv, monkeypatch, repo, key, basename):
    monkeypatch.setattr("sys.argv", ["show-image-baseline-version", key, basename])
    monkeypatch.setattr(sibv, "find_repo_root", lambda: repo)


def test_main_shows_both_baselines(sibv, repo, monkeypatch, capsys):
    write_baselines(repo, upgrade_docs="4.8.5", release_table="4.8.5")
    set_argv_and_repo(sibv, monkeypatch, repo, "zac", "zaakafhandelcomponent")
    sibv.main()  # success path: must not raise
    out = capsys.readouterr().out
    assert "=== upgrade_docs baseline ===" in out
    assert "=== release_table baseline ===" in out
    assert out.count(f"ghcr.io/infonl/zaakafhandelcomponent: 5.0.2  (sha256:{'a' * 64})") == 2
    assert "5.4.3" not in out  # must read the BASELINE tag's content, not HEAD


def test_main_no_pin_at_baseline_is_noted_not_fatal(sibv, repo, monkeypatch, capsys):
    """<key> <basename> not pinned at all at ONE baseline (the component
    relies entirely on its chart's own image default there, e.g.
    podiumd-4.9.0 in the `repo` fixture) is just a note there, not a
    crash overall — the other baseline still resolves fine."""
    write_baselines(repo, upgrade_docs="4.8.5", release_table="4.9.0")
    set_argv_and_repo(sibv, monkeypatch, repo, "zac", "zaakafhandelcomponent")

    sibv.main()  # upgrade_docs alone resolving is enough to succeed overall

    out = capsys.readouterr().out
    assert f"ghcr.io/infonl/zaakafhandelcomponent: 5.0.2  (sha256:{'a' * 64})" in out
    assert "no image pin with basename 'zaakafhandelcomponent' found under 'zac'" in out


def test_main_missing_release_table_key_is_noted_not_an_error(sibv, repo, monkeypatch, capsys):
    write_baselines(repo, upgrade_docs="4.8.5")
    set_argv_and_repo(sibv, monkeypatch, repo, "zac", "zaakafhandelcomponent")
    sibv.main()  # upgrade_docs alone is enough to succeed overall
    out = capsys.readouterr().out
    assert "=== upgrade_docs baseline ===" in out
    assert "release-baseline.yaml has no release_table key — skipping" in out


def test_main_unresolvable_baseline_noted_other_still_shown(sibv, repo, monkeypatch, capsys):
    write_baselines(repo, upgrade_docs="9.9.9", release_table="4.8.5")
    set_argv_and_repo(sibv, monkeypatch, repo, "zac", "zaakafhandelcomponent")
    sibv.main()  # release_table alone is enough to succeed overall
    out = capsys.readouterr().out
    assert "could not resolve baseline" in out
    assert f"5.0.2  (sha256:{'a' * 64})" in out


def test_main_neither_baseline_shown_fails(sibv, repo, monkeypatch, capsys):
    set_argv_and_repo(sibv, monkeypatch, repo, "zac", "zaakafhandelcomponent")
    with pytest.raises(SystemExit) as exc_info:
        sibv.main()
    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "release-baseline.yaml has no upgrade_docs key" in out
    assert "release-baseline.yaml has no release_table key" in out


def test_main_unknown_key_fails(sibv, repo, monkeypatch, capsys):
    write_baselines(repo, upgrade_docs="4.8.5", release_table="4.8.5")
    set_argv_and_repo(sibv, monkeypatch, repo, "totally-unknown", "zaakafhandelcomponent")
    with pytest.raises(SystemExit) as exc_info:
        sibv.main()
    assert exc_info.value.code == 1
    assert "no image pin with basename 'zaakafhandelcomponent' found under 'totally-unknown'" in capsys.readouterr().out


def test_main_requires_exactly_two_arguments(sibv, monkeypatch):
    monkeypatch.setattr("sys.argv", ["show-image-baseline-version"])
    with pytest.raises(SystemExit) as exc_info:
        sibv.main()
    assert exc_info.value.code == 1


def test_main_too_many_arguments_fails(sibv, monkeypatch):
    monkeypatch.setattr("sys.argv", ["show-image-baseline-version", "zac", "zaakafhandelcomponent", "extra"])
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
