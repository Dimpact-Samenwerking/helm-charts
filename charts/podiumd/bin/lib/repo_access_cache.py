"""JSON cache for check_repo_access (<repo-root>/.cache/repo-access-cache.json, gitignored).

Also used by cached_tag_exists, which adds a "digest" field to "registry:"
entries, so the image digest checks and check_repo_access share one cache
instead of re-querying the same pin. The [DIGEST-GONE] check never uses it.

Only successes are cached: caching a failure (e.g. a "Too Many Requests"
response) would outlive its cause. The TTL is short: enough to skip network
round trips on quick re-runs (avoiding Docker Hub's anonymous rate limit),
short enough to notice real access changes soon."""

from datetime import timedelta
from pathlib import Path
from typing import NotRequired
from typing import TypedDict
from typing import TypeGuard

from lib.json_cache import cache_file
from lib.json_cache import checked_within
from lib.json_cache import load_json_cache
from lib.json_cache import save_json_cache
from lib.yaml_types import shape_problem

CACHE_FILENAME = "repo-access-cache.json"


class RepoAccessEntry(TypedDict):
    """One cache entry: check time and, for registry entries, the digest found."""

    checked_at: str
    digest: NotRequired[str | None]


def is_repo_access_entry(value: object) -> TypeGuard[RepoAccessEntry]:
    """Whether a parsed cache entry is a RepoAccessEntry."""
    return shape_problem(value, {"checked_at": str, "digest?": (str, type(None))}) is None


def cache_path(chart_dir: Path):
    """Cache file path, rooted at the repo root so /.cache/ in .gitignore covers it.

    Falls back to chart_dir outside a git checkout."""
    return cache_file(chart_dir, CACHE_FILENAME)


def load_cache(chart_dir: Path) -> dict[str, RepoAccessEntry]:
    """Parsed cache, or {} if missing or corrupt; never raises."""
    return load_json_cache(cache_path(chart_dir), is_repo_access_entry)


def save_cache(chart_dir: Path, cache: dict[str, RepoAccessEntry]):
    """Persist `cache` as sorted, pretty-printed JSON."""
    save_json_cache(cache_path(chart_dir), cache)


def cache_key(test_kind: str, target: str | tuple[str, ...]):
    """Stable key: "http:<url>" or "registry:<host>/<repo_path>:<version>"."""
    if test_kind == "http":
        return f"http:{target}"
    host, repo_path, version = target
    return f"registry:{host}/{repo_path}:{version}"


def cache_entry_is_fresh(entry: RepoAccessEntry, ttl_minutes: float):
    """True when `entry` was checked within the last `ttl_minutes` minutes."""
    return checked_within(entry.get("checked_at"), timedelta(minutes=ttl_minutes))
