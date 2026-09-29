"""Git helpers for reading a chart's state at a baseline ref without checking it out."""

import re

from pathlib import Path

from lib.procutil import run
from lib.yaml_types import YamlMapping
from lib.yaml_types import parse_yaml_mapping


def find_repo_root(start_path: Path):
    """The repo root containing start_path, or None if not inside a git repository."""
    result = run(["git", "-C", str(start_path), "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if result.returncode != 0:
        return None
    return Path(result.stdout.strip())


def current_branch(repo_root: Path):
    """The current branch name, or "" if HEAD is detached."""
    result = run(["git", "-C", str(repo_root), "branch", "--show-current"], capture_output=True, text=True)
    return result.stdout.strip()


def baseline_ref_candidates(baseline: str):
    """Refs to try for baseline: a bare version maps to tag, then feature branch; any other ref as-is."""
    if re.match(r"^\d+\.\d+\.\d+", baseline):
        return [f"podiumd-{baseline}", f"origin/feature/podiumd-{baseline}", f"feature/podiumd-{baseline}"]
    return [baseline]


def resolve_git_ref(repo_root: Path, candidates: list[str]):
    """The first ref in candidates that resolves to a commit in repo_root, or None."""
    for ref in candidates:
        result = run(
            ["git", "-C", str(repo_root), "rev-parse", "--verify", "-q", f"{ref}^{{commit}}"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return ref
    return None


def resolve_baseline_ref(repo_root: Path, baseline: str):
    """Resolve baseline to a git ref. Returns (ref, error); error is None on success."""
    candidates = baseline_ref_candidates(baseline)
    ref = resolve_git_ref(repo_root, candidates)
    if ref:
        return ref, None
    return None, f"could not resolve baseline '{baseline}' to a git ref (tried {', '.join(candidates)})"


def git_show_text(repo_root: Path, ref: str, relpath: str) -> str | None:
    """The raw text of relpath at ref, or None if it doesn't exist there."""
    result = run(["git", "-C", str(repo_root), "show", f"{ref}:{relpath}"], capture_output=True, text=True)
    if result.returncode != 0:
        return None
    return result.stdout


def git_show_yaml(repo_root: Path, ref: str, relpath: str) -> YamlMapping | None:
    """relpath at ref parsed as a YAML mapping, or None if it doesn't exist there."""
    text = git_show_text(repo_root, ref, relpath)
    return parse_yaml_mapping(text, f"{ref}:{relpath}") if text is not None else None
