"""JSON cache for check_repo_access's own existence/reachability checks
(<repo-root>/.cache/repo-access-cache.json — same gitignored, personal,
per-checkout convention as lib.image_upgrade_cache) — deliberately NOT
shared with check_image_digests or anything else that needs the actual
digest value: this cache only ever records "reachable, as of this
timestamp" (a bool), never a digest, so a stale hit can never mask real
digest drift somewhere else. Worst case a hit just means check_repo_access
is up to REPO_ACCESS_CACHE_TTL_MINUTES behind on a repo/image that's
since gone away — "Image digests"/"Dependencies" (both uncached, and
each already the authoritative check for their own concern) still catch
that fresh regardless.

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
import json
from datetime import datetime, timedelta, timezone

from lib.gitutil import find_repo_root

CACHE_FILENAME = "repo-access-cache.json"
REPO_ACCESS_CACHE_TTL_MINUTES = 30


def cache_path(chart_dir):
    """<repo-root>/.cache/repo-access-cache.json — a personal, gitignored,
    per-checkout cache (same as lib.image_upgrade_cache's own). Rooted at
    the repo root (not chart_dir) so root .gitignore's plain /.cache/
    entry covers it without a chart-specific rule. Falls back to
    chart_dir itself if it isn't inside a git checkout."""
    root = find_repo_root(chart_dir) or chart_dir
    return root / ".cache" / CACHE_FILENAME


def load_cache(chart_dir):
    path = cache_path(chart_dir)
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_cache(chart_dir, cache):
    path = cache_path(chart_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, indent=2, sort_keys=True), encoding="utf-8")


def cache_key(test_kind, target):
    """A stable string key for one check_repo_access entry — test_kind is
    "http" (target a bare URL string) or "registry" (target a (host,
    repo_path, version) tuple)."""
    if test_kind == "http":
        return f"http:{target}"
    host, repo_path, version = target
    return f"registry:{host}/{repo_path}:{version}"


def cache_entry_is_fresh(entry):
    try:
        checked_at = datetime.fromisoformat(entry["checked_at"])
    except (KeyError, ValueError, TypeError):
        return False
    return datetime.now(timezone.utc) - checked_at < timedelta(minutes=REPO_ACCESS_CACHE_TTL_MINUTES)
