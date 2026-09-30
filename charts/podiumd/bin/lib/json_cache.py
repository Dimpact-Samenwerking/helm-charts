"""Personal, gitignored JSON cache files under <repo-root>/.cache/."""

import json

from collections.abc import Callable
from collections.abc import Mapping
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from pathlib import Path
from typing import TypeGuard
from typing import TypeVar

from lib.gitutil import find_repo_root
from lib.yaml_types import is_object_dict


def cache_file(chart_dir: Path, filename: str) -> Path:
    """<repo-root>/.cache/<filename>, or <chart_dir>/.cache/ outside a git checkout.

    Rooted at the repo root so the root .gitignore's /.cache/ entry covers it."""
    root = find_repo_root(chart_dir) or chart_dir
    return root / ".cache" / filename


EntryT = TypeVar("EntryT")


def load_json_cache(path: Path, is_entry: Callable[[object], TypeGuard[EntryT]]) -> dict[str, EntryT]:
    """The entries at path that pass is_entry; {} if missing or unparsable. Never raises."""
    if not path.is_file():
        return {}
    try:
        data: object = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not is_object_dict(data):
        return {}
    return {key: entry for key, entry in data.items() if isinstance(key, str) and is_entry(entry)}


def save_json_cache(path: Path, cache: Mapping[str, object]) -> None:
    """Write cache to path as indented, key-sorted JSON, creating the directory if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, indent=2, sort_keys=True), encoding="utf-8")


def checked_within(timestamp: object, max_age: timedelta) -> bool:
    """Whether the ISO `timestamp` a cache entry was recorded at is less than `max_age` old.

    A missing, malformed or timezone-less timestamp counts as stale, so the entry is refetched.
    """
    if not isinstance(timestamp, str):
        return False
    try:
        return datetime.now(timezone.utc) - datetime.fromisoformat(timestamp) < max_age
    except (ValueError, TypeError):
        return False
