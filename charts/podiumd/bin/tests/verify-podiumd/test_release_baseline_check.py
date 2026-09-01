"""check_release_baseline — release-baseline.yaml's two independent
baselines (upgrade_docs, release_table) must each resolve to a real
podiumd-<version> tag/branch. Unlike the old single release-baseline
file this replaced (where a wholly-absent file was fine, since older
releases/fresh checkouts predated it), release-baseline.yaml is
committed with real values from day one — a missing file, a missing
key, or a key present but unresolvable are all failures now, checked
independently per key."""
import subprocess

import pytest


def git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path):
    git("init", "-q", cwd=tmp_path)
    git("config", "user.email", "test@example.com", cwd=tmp_path)
    git("config", "user.name", "Test", cwd=tmp_path)
    (tmp_path / "README.md").write_text("placeholder\n", encoding="utf-8")
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "init", cwd=tmp_path)
    git("tag", "podiumd-4.8.5", cwd=tmp_path)
    git("tag", "podiumd-4.9.0", cwd=tmp_path)
    return tmp_path


def write_baselines(chart_dir, upgrade_docs=None, release_table=None):
    lines = []
    if upgrade_docs is not None:
        lines.append(f"upgrade_docs: '{upgrade_docs}'\n")
    if release_table is not None:
        lines.append(f"release_table: '{release_table}'\n")
    (chart_dir / "release-baseline.yaml").write_text("".join(lines), encoding="utf-8")


def test_both_baselines_resolve_passes(vp, repo, capsys):
    write_baselines(repo, upgrade_docs="4.9.0", release_table="4.8.5")
    ok, detail = vp.check_release_baseline(repo)
    assert ok is True
    assert "upgrade_docs -> podiumd-4.9.0" in detail
    assert "release_table -> podiumd-4.8.5" in detail
    out = capsys.readouterr().out
    assert "upgrade_docs '4.9.0' resolves to podiumd-4.9.0" in out
    assert "release_table '4.8.5' resolves to podiumd-4.8.5" in out


def test_missing_file_fails_both_keys(vp, repo):
    ok, detail = vp.check_release_baseline(repo)
    assert ok is False
    assert "upgrade_docs: missing from release-baseline.yaml" in detail
    assert "release_table: missing from release-baseline.yaml" in detail


def test_missing_upgrade_docs_key_fails_even_if_release_table_present(vp, repo):
    write_baselines(repo, release_table="4.8.5")
    ok, detail = vp.check_release_baseline(repo)
    assert ok is False
    assert "upgrade_docs: missing from release-baseline.yaml" in detail


def test_missing_release_table_key_fails_even_if_upgrade_docs_present(vp, repo):
    write_baselines(repo, upgrade_docs="4.9.0")
    ok, detail = vp.check_release_baseline(repo)
    assert ok is False
    assert "release_table: missing from release-baseline.yaml" in detail


def test_unresolvable_baseline_fails(vp, repo):
    write_baselines(repo, upgrade_docs="9.9.9", release_table="4.8.5")
    ok, detail = vp.check_release_baseline(repo)
    assert ok is False
    assert "upgrade_docs '9.9.9'" in detail
    assert "could not resolve" in detail


def test_one_resolves_one_fails_the_passing_key_is_still_reported_ok(vp, repo, capsys):
    write_baselines(repo, upgrade_docs="4.9.0", release_table="9.9.9")
    ok, detail = vp.check_release_baseline(repo)
    assert ok is False
    assert "release_table '9.9.9'" in detail
    out = capsys.readouterr().out
    assert "upgrade_docs '4.9.0' resolves to podiumd-4.9.0" in out


def test_not_a_git_repo_fails(vp, tmp_path):
    ok, detail = vp.check_release_baseline(tmp_path)
    assert ok is False
    assert "not inside a git repository" in detail
