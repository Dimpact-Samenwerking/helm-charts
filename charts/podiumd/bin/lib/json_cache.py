"""The personal, gitignored JSON cache files under <repo-root>/.cache/,
shared by lib.checks.cve, lib.image.upgrade_cache and lib.repo_access_cache."""

import json

from pathlib import Path

from lib.gitutil import find_repo_root


def cache_file(chart_dir: Path, filename: str) -> Path:
    """<repo-root>/.cache/<filename>. Rooted at the repo root (not
    chart_dir) so root .gitignore's plain /.cache/ entry covers it without
    a chart-specific rule. Falls back to chart_dir itself if it isn't
    inside a git checkout."""
    root = find_repo_root(chart_dir) or chart_dir
    return root / ".cache" / filename


def load_json_cache(path: Path) -> dict:
    """The parsed contents of path, or {} if the file doesn't exist yet or
    can't be parsed (corrupt/truncated). Never raises, so a broken cache
    behaves like a cold one."""
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_json_cache(path: Path, cache: dict) -> None:
    """Write cache to path as pretty-printed, key-sorted JSON, creating the
    .cache directory first if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, indent=2, sort_keys=True), encoding="utf-8")
