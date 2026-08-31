"""lib.gitutil — find_repo_root, current_branch, baseline_ref_candidates,
resolve_git_ref, resolve_baseline_ref, git_show_yaml, against a real,
hermetic temp git repo."""
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
    (tmp_path / "values.yaml").write_text(yaml.safe_dump({"zac": {"image": {"tag": "5.0.2"}}}))
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "baseline", cwd=tmp_path)
    git("tag", "podiumd-4.8.5", cwd=tmp_path)

    (tmp_path / "values.yaml").write_text(yaml.safe_dump({"zac": {"image": {"tag": "5.1.0"}}}))
    git("add", "-A", cwd=tmp_path)
    git("commit", "-q", "-m", "bump zac", cwd=tmp_path)
    return tmp_path


# --- find_repo_root ---

def test_find_repo_root_finds_toplevel(libgitutil, repo):
    (repo / "sub").mkdir()
    assert libgitutil.find_repo_root(repo / "sub").resolve() == repo.resolve()


def test_find_repo_root_none_outside_a_repo(libgitutil, tmp_path):
    outside = tmp_path / "not-a-repo"
    outside.mkdir()
    assert libgitutil.find_repo_root(outside) is None


# --- current_branch ---

def test_current_branch_reads_branch_name(libgitutil, repo):
    git("checkout", "-q", "-b", "feature/podiumd-4.10.0", cwd=repo)
    assert libgitutil.current_branch(repo) == "feature/podiumd-4.10.0"


def test_current_branch_empty_on_detached_head(libgitutil, repo):
    head_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                               capture_output=True, text=True, check=True).stdout.strip()
    git("checkout", "-q", head_sha, cwd=repo)
    assert libgitutil.current_branch(repo) == ""


# --- baseline_ref_candidates ---

def test_baseline_ref_candidates_bare_version(libgitutil):
    assert libgitutil.baseline_ref_candidates("4.8.5") == [
        "podiumd-4.8.5", "origin/feature/podiumd-4.8.5", "feature/podiumd-4.8.5"
    ]


def test_baseline_ref_candidates_explicit_ref(libgitutil):
    assert libgitutil.baseline_ref_candidates("origin/some-branch") == ["origin/some-branch"]
    assert libgitutil.baseline_ref_candidates("abc1234") == ["abc1234"]


# --- resolve_git_ref ---

def test_resolve_git_ref_finds_tag(libgitutil, repo):
    assert libgitutil.resolve_git_ref(repo, ["nonexistent", "podiumd-4.8.5"]) == "podiumd-4.8.5"


def test_resolve_git_ref_none_when_nothing_resolves(libgitutil, repo):
    assert libgitutil.resolve_git_ref(repo, ["nope-1", "nope-2"]) is None


# --- resolve_baseline_ref ---

def test_resolve_baseline_ref_resolves_the_tag(libgitutil, repo):
    ref, error = libgitutil.resolve_baseline_ref(repo, "4.8.5")
    assert ref == "podiumd-4.8.5"
    assert error is None


def test_resolve_baseline_ref_error_names_every_candidate_tried(libgitutil, repo):
    ref, error = libgitutil.resolve_baseline_ref(repo, "9.9.9")
    assert ref is None
    assert error == (
        "could not resolve baseline '9.9.9' to a git ref "
        "(tried podiumd-9.9.9, origin/feature/podiumd-9.9.9, feature/podiumd-9.9.9)"
    )


# --- git_show_yaml ---

def test_git_show_yaml_reads_historical_content(libgitutil, repo):
    data = libgitutil.git_show_yaml(repo, "podiumd-4.8.5", "values.yaml")
    assert data["zac"]["image"]["tag"] == "5.0.2"
    data_head = libgitutil.git_show_yaml(repo, "HEAD", "values.yaml")
    assert data_head["zac"]["image"]["tag"] == "5.1.0"


def test_git_show_yaml_none_for_missing_file(libgitutil, repo):
    assert libgitutil.git_show_yaml(repo, "HEAD", "does-not-exist.yaml") is None
