"""Gitignored JSON cache of image-upgrade tag lookups, written by upgrade_check and read by checks.cve.

Its own module to avoid a circular import between those two.
"""

from datetime import timedelta
from pathlib import Path
from typing import TypedDict
from typing import TypeGuard

from lib.json_cache import cache_file
from lib.json_cache import checked_within
from lib.json_cache import load_json_cache
from lib.json_cache import save_json_cache
from lib.yaml_types import shape_problem

CACHE_FILENAME = "image-upgrade-cache.json"


class UpgradeEntry(TypedDict):
    """When the tag list was checked, and the newest same-variant tag then (the pin itself if none newer)."""

    checked_at: str
    newest: str


def is_upgrade_entry(value: object) -> TypeGuard[UpgradeEntry]:
    """Whether a parsed cache entry is an UpgradeEntry."""
    return shape_problem(value, {"checked_at": str, "newest": str}) is None


def cache_path(chart_dir: Path):
    """<repo-root>/.cache/image-upgrade-cache.json, or under chart_dir outside a git checkout.

    Repo root so the root .gitignore's /.cache/ covers it.
    """
    return cache_file(chart_dir, CACHE_FILENAME)


def load_cache(chart_dir: Path) -> dict[str, UpgradeEntry]:
    """The cache at cache_path(chart_dir); {} if missing or corrupt (lookups then re-fetch)."""
    return load_json_cache(cache_path(chart_dir), is_upgrade_entry)


def save_cache(chart_dir: Path, cache: dict[str, UpgradeEntry]):
    """Write `cache` as key-sorted JSON, creating .cache/ if needed.

    Called after each live check, so an interrupted run keeps its results.
    """
    save_json_cache(cache_path(chart_dir), cache)


def cache_key(repository: str, version: str):
    """The cache key of a pin, e.g. "example.com/repo:1.2.3"."""
    return f"{repository}:{version}"


def cache_entry_is_fresh(entry: UpgradeEntry, ttl_days: int):
    """Whether `entry` was checked within the last `ttl_days` days."""
    return checked_within(entry.get("checked_at"), timedelta(days=ttl_days))
