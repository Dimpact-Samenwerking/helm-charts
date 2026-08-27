"""JSON cache for image-upgrade-tag lookups
(charts/podiumd/.cache/image-upgrade-cache.json — a personal, gitignored,
per-checkout cache, see cache_path), shared by lib.image_upgrade_check
(which populates it via a live registry check) and lib.cve_check (which
reads it read-only, to annotate a CVE finding as "upgradable" without
triggering a registry round trip of its own — see that module's
docstring). Split into its own module because both need it: cve_check
importing from image_upgrade_check (or vice versa) would be circular,
since image_upgrade_check already imports classification helpers from
cve_check."""
import json
from datetime import datetime, timedelta, timezone

CACHE_FILENAME = "image-upgrade-cache.json"

# A new tag can be published at any moment, so this is deliberately much
# shorter than cve_check's CVE_CACHE_TTL_DAYS — see lib.image_upgrade_check's
# docstring for the full rationale.
IMAGE_UPGRADE_CACHE_TTL_DAYS = 1


def cache_path(chart_dir):
    """charts/podiumd/.cache/image-upgrade-cache.json — a personal,
    gitignored, per-checkout cache (same as cve_check's own), never
    committed."""
    return chart_dir / ".cache" / CACHE_FILENAME


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


def cache_key(repository, version):
    return f"{repository}:{version}"


def cache_entry_is_fresh(entry):
    try:
        checked_at = datetime.fromisoformat(entry["checked_at"])
    except (KeyError, ValueError, TypeError):
        return False
    return datetime.now(timezone.utc) - checked_at < timedelta(days=IMAGE_UPGRADE_CACHE_TTL_DAYS)
