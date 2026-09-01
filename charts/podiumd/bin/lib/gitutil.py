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


def current_branch(repo_root):
    """The current branch name, or "" if HEAD is detached (`git branch
    --show-current` returns nothing in that case)."""
    result = run(["git", "-C", str(repo_root), "branch", "--show-current"],
                 capture_output=True, text=True)
    return result.stdout.strip()


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


def resolve_baseline_ref(repo_root, baseline):
    """baseline_ref_candidates + resolve_git_ref, with a ready-to-print
    error message on a miss — shared by every caller that must refuse an
    unresolvable baseline (change-podiumd-baseline, create-podiumd-version,
    verify-podiumd's release-baseline check). Returns (ref, error): error
    is None on success."""
    candidates = baseline_ref_candidates(baseline)
    ref = resolve_git_ref(repo_root, candidates)
    if ref:
        return ref, None
    return None, f"could not resolve baseline '{baseline}' to a git ref (tried {', '.join(candidates)})"


def git_show_text(repo_root, ref, relpath):
    """The raw text of relpath as it was at ref, or None if it doesn't
    exist there — for a caller that needs values.yaml's own literal
    lines (e.g. lib.image_version's scan_digest_pins/dotted_key_path
    text scanners), not its parsed structure."""
    result = run(["git", "-C", str(repo_root), "show", f"{ref}:{relpath}"], capture_output=True, text=True)
    if result.returncode != 0:
        return None
    return result.stdout


def git_show_yaml(repo_root, ref, relpath):
    text = git_show_text(repo_root, ref, relpath)
    return yaml.safe_load(text) if text is not None else None
