"""Git helpers shared by every script that reads a chart's historical state
at a baseline release without checking it out."""
import re
from pathlib import Path

import yaml

from lib.procutil import run


def find_repo_root(start_path):
    """The repo root containing start_path, or None if it isn't inside a git
    repository — callers that treat this as a hard precondition should raise
    themselves; some (e.g. a baseline lookup) treat a miss as recoverable."""
    result = run(["git", "-C", str(start_path), "rev-parse", "--show-toplevel"],
                 capture_output=True, text=True)
    if result.returncode != 0:
        return None
    return Path(result.stdout.strip())


def baseline_ref_candidates(baseline):
    """A bare version like "4.8.5" is resolved to the release tag first, then
    the (possibly not-yet-merged) feature branch. An explicit ref is used as-is."""
    if re.match(r"^\d+\.\d+\.\d+", baseline):
        return [f"podiumd-{baseline}", f"origin/feature/podiumd-{baseline}", f"feature/podiumd-{baseline}"]
    return [baseline]


def resolve_git_ref(repo_root, candidates):
    for ref in candidates:
        result = run(["git", "-C", str(repo_root), "rev-parse", "--verify", "-q", f"{ref}^{{commit}}"],
                     capture_output=True, text=True)
        if result.returncode == 0:
            return ref
    return None


def git_show_yaml(repo_root, ref, relpath):
    result = run(["git", "-C", str(repo_root), "show", f"{ref}:{relpath}"], capture_output=True, text=True)
    if result.returncode != 0:
        return None
    return yaml.safe_load(result.stdout)
