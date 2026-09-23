"""JSON cache for image-upgrade-tag lookups
(<repo-root>/.cache/image-upgrade-cache.json — a personal, gitignored,
per-checkout cache, see cache_path), shared by lib.image.upgrade_check
(which populates it via a live registry check) and lib.checks.cve (which
reads it read-only, to annotate a CVE finding as "upgradable" without
triggering a registry round trip of its own — see that module's
docstring). Split into its own module because both need it: cve_check
importing from image_upgrade_check (or vice versa) would be circular,
since image_upgrade_check already imports classification helpers from
cve_check."""

from datetime import datetime
from datetime import timedelta
from datetime import timezone

from lib.json_cache import cache_file
from lib.json_cache import load_json_cache
from lib.json_cache import save_json_cache

CACHE_FILENAME = "image-upgrade-cache.json"


def cache_path(chart_dir):
    """<repo-root>/.cache/image-upgrade-cache.json — a personal,
    gitignored, per-checkout cache (same as cve_check's own), never
    committed. Rooted at the repo root (not chart_dir) so root
    .gitignore's plain /.cache/ entry covers it without a chart-specific
    rule. Falls back to chart_dir itself if it isn't inside a git
    checkout."""
    return cache_file(chart_dir, CACHE_FILENAME)


def load_cache(chart_dir):
    """The cache dict at cache_path(chart_dir), or {} if it doesn't exist
    yet or fails to parse (a corrupt/partial cache file is treated the
    same as no cache at all, never raised — every lookup just misses and
    gets re-fetched from the registry)."""
    return load_json_cache(cache_path(chart_dir))


def save_cache(chart_dir, cache):
    """Write `cache` to cache_path(chart_dir) as pretty, key-sorted JSON,
    creating the .cache/ directory if needed. check_image_upgrades calls
    this incrementally after each live registry check (not just once at
    the end), so a run interrupted partway still keeps whatever it
    already fetched."""
    save_json_cache(cache_path(chart_dir), cache)


def cache_key(repository, version):
    """The cache dict key for a given (repository, version) pin — e.g.
    "example.com/repo:1.2.3" — shared by both load_cache/save_cache
    callers (lib.image.upgrade_check and lib.checks.cve) so they always
    agree on the same key shape."""
    return f"{repository}:{version}"


def cache_entry_is_fresh(entry, ttl_days):
    """True when `entry` was checked within the last `ttl_days` days (see
    image_upgrade_check.tag_check_cache_ttl_days in lib.settings — a new
    tag can be published at any moment, so this is deliberately much
    shorter than cve_scan.scan_cache_ttl_days; see lib.image.upgrade_
    check's docstring for the full rationale)."""
    try:
        checked_at = datetime.fromisoformat(entry["checked_at"])
    except (KeyError, ValueError, TypeError):
        return False
    return datetime.now(timezone.utc) - checked_at < timedelta(days=ttl_days)
