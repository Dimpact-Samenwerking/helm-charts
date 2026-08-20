"""find_repo_root, resolve_git_ref, git_show_yaml — against a real, hermetic
temp git repo (not the actual project repo)."""
import subprocess

import pytest


def git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path):
    git("init", "-q", cwd=tmp_path)
    git("config", "user.email", "test@example.com", cwd=tmp_path)
    git("config", "user.name", "Test", cwd=tmp_path)
    (tmp_path / "values.yaml").write_text("zac:\n  enabled: true\n")
    git("add", "values.yaml", cwd=tmp_path)
    git("commit", "-q", "-m", "initial", cwd=tmp_path)
    git("tag", "podiumd-1.0.0", cwd=tmp_path)
    (tmp_path / "values.yaml").write_text("zac:\n  enabled: false\n")
    git("add", "values.yaml", cwd=tmp_path)
    git("commit", "-q", "-m", "second", cwd=tmp_path)
    return tmp_path


def test_find_repo_root_returns_the_repo_root(vp, repo):
    subdir = repo / "sub"
    subdir.mkdir()
    assert vp.find_repo_root(subdir).resolve() == repo.resolve()


def test_find_repo_root_returns_none_outside_a_repo(vp, tmp_path_factory):
    outside = tmp_path_factory.mktemp("not-a-repo")
    assert vp.find_repo_root(outside) is None


def test_resolve_git_ref_finds_existing_tag(vp, repo):
    assert vp.resolve_git_ref(repo, ["nonexistent-ref", "podiumd-1.0.0"]) == "podiumd-1.0.0"


def test_resolve_git_ref_returns_none_when_nothing_resolves(vp, repo):
    assert vp.resolve_git_ref(repo, ["nonexistent-1", "nonexistent-2"]) is None


def test_git_show_yaml_reads_file_at_ref(vp, repo):
    data = vp.git_show_yaml(repo, "podiumd-1.0.0", "values.yaml")
    assert data == {"zac": {"enabled": True}}
    data_head = vp.git_show_yaml(repo, "HEAD", "values.yaml")
    assert data_head == {"zac": {"enabled": False}}


def test_git_show_yaml_returns_none_for_missing_file(vp, repo):
    assert vp.git_show_yaml(repo, "HEAD", "does-not-exist.yaml") is None


def test_git_show_yaml_returns_none_for_bad_ref(vp, repo):
    assert vp.git_show_yaml(repo, "not-a-real-ref", "values.yaml") is None
