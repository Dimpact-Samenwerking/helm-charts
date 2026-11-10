"""find_repo_root, resolve_git_ref — against a real, hermetic
temp git repo (not the actual project repo)."""

from pathlib import Path
from types import ModuleType

import pytest

from tests.git_repo import git
from tests.git_repo import init_git_repo


@pytest.fixture
def repo(tmp_path: Path):
    init_git_repo(tmp_path)
    (tmp_path / "values.yaml").write_text("zac:\n  enabled: true\n")
    git("add", "values.yaml", cwd=tmp_path)
    git("commit", "-q", "-m", "initial", cwd=tmp_path)
    git("tag", "podiumd-1.0.0", cwd=tmp_path)
    (tmp_path / "values.yaml").write_text("zac:\n  enabled: false\n")
    git("add", "values.yaml", cwd=tmp_path)
    git("commit", "-q", "-m", "second", cwd=tmp_path)
    return tmp_path


def test_find_repo_root_returns_the_repo_root(libgitutil: ModuleType, repo):
    subdir = repo / "sub"
    subdir.mkdir()
    assert libgitutil.find_repo_root(subdir).resolve() == repo.resolve()


def test_find_repo_root_returns_none_outside_a_repo(libgitutil: ModuleType, tmp_path_factory: pytest.TempPathFactory):
    outside = tmp_path_factory.mktemp("not-a-repo")
    assert libgitutil.find_repo_root(outside) is None


def test_resolve_git_ref_finds_existing_tag(libgitutil: ModuleType, repo):
    assert libgitutil.resolve_git_ref(repo, ["nonexistent-ref", "podiumd-1.0.0"]) == "podiumd-1.0.0"


def test_resolve_git_ref_returns_none_when_nothing_resolves(libgitutil: ModuleType, repo):
    assert libgitutil.resolve_git_ref(repo, ["nonexistent-1", "nonexistent-2"]) is None
