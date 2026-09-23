"""JSON cache for check_repo_access's own existence/reachability checks
(<repo-root>/.cache/repo-access-cache.json — same gitignored, personal,
per-checkout convention as lib.image.upgrade_cache).

Also shared, as of the same fix that added lib.image.digests._cached_
tag_exists' own disk tier: an entry here can ALSO carry a "digest" field
alongside "checked_at" — check_repo_access itself never sets or reads
that field (it only ever needed a bare reachability bool), but check_
image_digests/find_sliding_pins (via cached_tag_exists) both read AND
write it, for a "registry:" entry specifically, so the two no longer
each independently re-query the registry for the same pin within one
verify-podiumd run. Same cache_key/load_cache/save_cache/cache_entry_
is_fresh functions, same file, same TTL — genuinely one cache, not two
parallel ones that happen to use the same format. Worst case a hit just
means whichever caller reads it is up to repo_access.cache_ttl_minutes
(lib.settings) behind on a repo/image (or digest) that's since changed —
"Dependencies"
(uncached, and the authoritative check for its own concern) still
catches that fresh regardless, and check_image_digests' own [DIGEST-
GONE] follow-up check is deliberately never routed through this cache
at all (see lib.image.digests' own docstring there).

Also only ever caches a SUCCESS. A failure is never written to the
cache and always re-checked next run — caching a failure risks
perpetuating a transient problem (e.g. this whole module's own reason
for existing: a registry's "Too Many Requests" rate-limit response)
well past whatever actually caused it, and could hide a real repo/image
coming back up sooner than the TTL would otherwise reveal.

Short TTL — long enough to skip a network round trip on a verify-podiumd
re-run minutes or a couple of hours later while iterating on something
unrelated (the actual, observed trigger for hitting Docker Hub's
anonymous pull-rate limit during this session), short enough that a
real access change is still caught again soon."""

from datetime import datetime
from datetime import timedelta
from datetime import timezone
from pathlib import Path

from lib.json_cache import cache_file
from lib.json_cache import load_json_cache
from lib.json_cache import save_json_cache

CACHE_FILENAME = "repo-access-cache.json"


def cache_path(chart_dir: Path):
    """<repo-root>/.cache/repo-access-cache.json — a personal, gitignored,
    per-checkout cache (same as lib.image.upgrade_cache's own). Rooted at
    the repo root (not chart_dir) so root .gitignore's plain /.cache/
    entry covers it without a chart-specific rule. Falls back to
    chart_dir itself if it isn't inside a git checkout."""
    return cache_file(chart_dir, CACHE_FILENAME)


def load_cache(chart_dir: Path):
    """The parsed contents of cache_path(chart_dir), or {} if the file
    doesn't exist yet or can't be parsed (corrupt/truncated) — never
    raises, so a broken cache just behaves like a cold one."""
    return load_json_cache(cache_path(chart_dir))


def save_cache(chart_dir: Path, cache: dict):
    """Persist `cache` to cache_path(chart_dir) as pretty-printed,
    key-sorted JSON, creating the .cache directory first if needed."""
    save_json_cache(cache_path(chart_dir), cache)


def cache_key(test_kind: str, target: str | tuple[str, ...]):
    """A stable string key for one check_repo_access entry — test_kind is
    "http" (target a bare URL string) or "registry" (target a (host,
    repo_path, version) tuple)."""
    if test_kind == "http":
        return f"http:{target}"
    host, repo_path, version = target
    return f"registry:{host}/{repo_path}:{version}"


def cache_entry_is_fresh(entry: dict, ttl_minutes: int):
    """True when `entry` was checked within the last `ttl_minutes`
    minutes (see repo_access.cache_ttl_minutes in lib.settings —
    deliberately short: long enough to skip a network round trip on a
    verify-podiumd re-run minutes or a couple of hours later while
    iterating on something unrelated, short enough that a real access
    change is still caught again soon; see this module's own docstring
    for the full rationale, including the Docker Hub rate-limit incident
    that motivated it)."""
    try:
        checked_at = datetime.fromisoformat(entry["checked_at"])
    except (KeyError, ValueError, TypeError):
        return False
    return datetime.now(timezone.utc) - checked_at < timedelta(minutes=ttl_minutes)
