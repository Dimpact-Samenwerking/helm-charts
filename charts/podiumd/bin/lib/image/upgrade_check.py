"""Report-only check for newer same-variant tags of every pinned image in values.yaml (see scan_image_pins).

Per image it lists the newest newer tag in each major, so a same-major upgrade
(postgres 16.x while 18 is out) shows next to the newest release.

Images are split into own/partner-vendor/other-vendor buckets using
lib.checks.cve's classification; only partner-vendor entries carry a
vendor label. A bucket is printed only if it has an upgradable image; "OK"
only when nothing is upgradable. Separate from the CVE check: a newer tag
doesn't imply a fix.

Tag lists are cached per (repository, version) in the gitignored
.cache/image-upgrade-cache.json, with a much shorter TTL than the CVE cache
since a new tag can appear any moment. Never fails on findings.
"""

import urllib.error

from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import TypedDict

from lib.checks.cve import BUCKETS
from lib.checks.cve import ImageClassification
from lib.checks.cve import bucket_of
from lib.checks.cve import bucket_title
from lib.checks.cve import classify_rendered_images
from lib.checks.cve import refs_by_bucket
from lib.checks.cve import target_label
from lib.image.digests import ImageTarget
from lib.image.digests import unique_image_targets
from lib.image.upgrade_cache import UpgradeEntry
from lib.image.upgrade_cache import cache_entry_is_fresh
from lib.image.upgrade_cache import cache_key
from lib.image.upgrade_cache import load_cache
from lib.image.upgrade_cache import save_cache
from lib.registry import find_newer_same_variant_tags
from lib.registry import parse_repo
from lib.settings import image_upgrade_tag_check_cache_ttl_days


@dataclass
class UpgradeCheckContext:
    """The per-scan inputs of _resolve_target_upgrade: label lookups and cache state."""

    classification: ImageClassification
    values_lines: list[str]
    old_cache: dict[str, UpgradeEntry]
    ttl_days: int


class ImageUpgrade(TypedDict):
    """One image in the upgrade report: its bucket, vendor label (partner
    only) and the newest newer same-variant tag per major."""

    bucket: str
    vendor_label: str | None
    newer: list[str]


@dataclass
class ImageUpgradeScan:
    """A completed registry-check pass: per-ref info, the three buckets, fetch-error and cache-hit stats."""

    images: dict[str, ImageUpgrade]
    own_refs: list[str]
    partner_refs: list[str]
    other_refs: list[str]
    fetch_errors: list[str]
    cache_hits: int


def _upgrade_info(label: str, newer: list[str]) -> ImageUpgrade:
    """One images[] entry: bucket, vendor-label suffix (partner-vendor only) and the newer tags."""
    return {
        "bucket": bucket_of(label),
        "vendor_label": label if bucket_of(label) == "partner" else None,
        "newer": newer,
    }


@dataclass
class _TargetResolveInfo:
    """A target's identity, resolved once for both the cache-hit and fetch paths."""

    image_ref: str
    key: str
    host: str
    repo_path: str
    version: str
    label: str


@dataclass
class _TargetResult:
    """One target's outcome; on a fetch failure only image_ref and error=True are meaningful."""

    image_ref: str
    key: str | None = None
    cache_entry: UpgradeEntry | None = None
    info: ImageUpgrade | None = None
    cache_hit: bool = False
    error: bool = False


def _fetch_target_upgrade(i: int, total: int, info: _TargetResolveInfo) -> _TargetResult:
    """Announce and run the registry tag-list call (cache hits stay silent)."""
    print(f"  [{i}/{total}] checking {info.image_ref} for a newer tag...", flush=True)
    try:
        newer = find_newer_same_variant_tags(info.host, info.repo_path, info.version)
    except (urllib.error.URLError, OSError) as e:
        print(f"  [FETCH-ERR] {info.image_ref}  {e}")
        return _TargetResult(info.image_ref, error=True)

    cache_entry: UpgradeEntry = {"checked_at": datetime.now(timezone.utc).isoformat(), "newer": newer}
    return _TargetResult(info.image_ref, info.key, cache_entry, _upgrade_info(info.label, newer))


def _resolve_target_upgrade(
    i: int, total: int, target: tuple[ImageTarget, tuple[str | None, int]], ctx: UpgradeCheckContext
) -> _TargetResult:
    """Resolve one target from a fresh cache entry or the registry."""
    (repository, version), (digest, line) = target
    host, repo_path = parse_repo(repository)
    info = _TargetResolveInfo(
        f"{host}/{repo_path}:{version}",
        cache_key(repository, version),
        host,
        repo_path,
        version,
        target_label(ctx.classification, ctx.values_lines, (repository, version, digest), line),
    )
    cached = ctx.old_cache.get(info.key)

    if cached and cache_entry_is_fresh(cached, ctx.ttl_days):
        result_info = _upgrade_info(info.label, cached["newer"])
        return _TargetResult(info.image_ref, info.key, cached, result_info, cache_hit=True)

    return _fetch_target_upgrade(i, total, info)


def _scan_image_upgrades(
    chart_dir: Path, targets: list[tuple[ImageTarget, tuple[str | None, int]]], ctx: UpgradeCheckContext
) -> ImageUpgradeScan:
    """Resolve every target, saving the cache after each registry call and at the end (drops stale entries)."""
    new_cache: dict[str, UpgradeEntry] = {}
    cache_hits = 0
    images: dict[str, ImageUpgrade] = {}
    fetch_errors: list[str] = []

    for i, target in enumerate(targets, 1):
        r = _resolve_target_upgrade(i, len(targets), target, ctx)
        if r.error or r.key is None or r.cache_entry is None or r.info is None:
            fetch_errors.append(r.image_ref)
            continue
        new_cache[r.key] = r.cache_entry
        if r.cache_hit:
            cache_hits += 1
        else:
            save_cache(chart_dir, new_cache)  # persist incrementally
        images[r.image_ref] = r.info

    save_cache(chart_dir, new_cache)  # drop entries for images no longer pinned

    own_refs, partner_refs, other_refs = refs_by_bucket(images)
    return ImageUpgradeScan(images, own_refs, partner_refs, other_refs, fetch_errors, cache_hits)


def _print_image_upgrade_findings(scan: ImageUpgradeScan, total: int, ttl_days: int):
    """Print the bucket sections, OK/fetch-error lines and cache summary.

    OK only when every image was checked: with fetch errors "no newer tag"
    would be vacuously true.
    """
    for bucket, refs in zip(BUCKETS, (scan.own_refs, scan.partner_refs, scan.other_refs), strict=True):
        print_upgradable(bucket_title(bucket, "images"), refs, scan.images)

    if scan.fetch_errors:
        print(f"INCOMPLETE: {len(scan.fetch_errors)}/{total} image(s) could not be checked for a newer tag")
    elif not any(info["newer"] for info in scan.images.values()):
        print("OK: no newer tag published for any pinned image")

    if scan.fetch_errors:
        print(f"{len(scan.fetch_errors)} image(s) could not be checked:")
        for ref in scan.fetch_errors:
            print(f"  {ref}")
    print(f"{scan.cache_hits}/{total} image(s) served from cache (checked within the last {ttl_days} day(s))")


def _image_upgrade_detail(scan: ImageUpgradeScan):
    own_n, own_up = bucket_totals(scan.own_refs, scan.images)
    partner_n, partner_up = bucket_totals(scan.partner_refs, scan.images)
    other_n, other_up = bucket_totals(scan.other_refs, scan.images)
    return (
        f"upgradable: {own_up}/{own_n} own, {partner_up}/{partner_n} partner-vendor, "
        f"{other_up}/{other_n} other-vendor; {len(scan.fetch_errors)} fetch error(s)"
    )


def check_image_upgrades(chart_dir: Path, extra_args: list[str]):
    """verify-podiumd check: report pinned images with a newer same-variant tag.

    Returns (True, "upgradable: X/Y own, ...") regardless of findings, or
    (False, "helm template failed to render") if the render fails.
    """
    ttl_days = image_upgrade_tag_check_cache_ttl_days(chart_dir)

    classification = classify_rendered_images(chart_dir, extra_args)
    if classification is None:
        return False, "helm template failed to render"

    values_path = chart_dir / "values.yaml"
    values_lines = values_path.read_text(encoding="utf-8").splitlines()
    targets = sorted(unique_image_targets(chart_dir).items())

    ctx = UpgradeCheckContext(classification, values_lines, load_cache(chart_dir), ttl_days)
    print(f"Checking {len(targets)} unique pinned image(s) for a newer published tag...")
    scan = _scan_image_upgrades(chart_dir, targets, ctx)

    _print_image_upgrade_findings(scan, len(targets), ttl_days)
    return True, _image_upgrade_detail(scan)


def bucket_totals(refs: list[str], images: dict[str, ImageUpgrade]) -> tuple[int, int]:
    """(total, upgradable_count) for one bucket's `refs`."""
    return len(refs), sum(1 for ref in refs if images[ref]["newer"])


def print_upgradable(title: str, refs: list[str], images: dict[str, ImageUpgrade]) -> None:
    """Print `title` and each upgradable ref with its vendor label; nothing if none is upgradable."""
    upgradable = [ref for ref in refs if images[ref]["newer"]]
    if not upgradable:
        return
    print(f"--- {title} ---")
    for ref in upgradable:
        info = images[ref]
        vendor = f" [{info['vendor_label']}]" if info["vendor_label"] else ""
        print(f"{ref}{vendor}: newest tag per major: {', '.join(info['newer'])}")
