"""A throwaway git repository for the tests that read tags, history or the work tree."""

import subprocess

from pathlib import Path


def git(*args: str, cwd: Path) -> None:
    """Run `git <args>` in `cwd`, failing the test on a non-zero exit."""
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def init_git_repo(path: Path) -> None:
    """An empty repository at `path` with a committer identity, so commits work on any machine."""
    git("init", "-q", cwd=path)
    git("config", "user.email", "test@example.com", cwd=path)
    git("config", "user.name", "Test", cwd=path)


def commit_all(path: Path, message: str) -> None:
    """Stage everything under `path` and commit it as `message`."""
    git("add", "-A", cwd=path)
    git("commit", "-q", "-m", message, cwd=path)


def commit_tagged(path: Path, message: str, version: str) -> None:
    """Commit everything and tag it podiumd-<version>, as a release the scripts can use as baseline."""
    commit_all(path, message)
    git("tag", f"podiumd-{version}", cwd=path)
