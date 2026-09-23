"""Report-only check for whether a numerically-newer same-variant tag is
currently published for every unique digest-pinned image in values.yaml,
split into the same own/partner-vendor/other-vendor buckets as
check_yamllint/check_kubeconform/check_shellcheck/check_kube_score/
check_cves. Classification itself is reused directly from lib.checks.cve
(own always wins from the `helm template` render's "# Source:"
attribution, falling back to a values.yaml top-level-key heuristic for a
component not present in the render at all — see that module's docstring
for the full rationale). Every bucket is itemized the same way (only the
images with an upgrade available — nothing to say about a clean image),
and, like every bucket here, only printed at all when at least one of its
images has an upgrade available. Other-vendor's own entries never carry a
vendor-label suffix the way partner-vendor's do — "other" is the leftover
bucket for a chart with no real vendor name to show, so there's nothing
meaningful to print beyond the ref itself (the same reason "own" images
never carry one either). Prints an explicit "OK" line only when NOTHING
anywhere is upgradable; per-bucket totals (upgradable/total, including
clean images) are always in the one-line summary regardless.

Split out of check_cves, where this used to live folded into its summary
line: "does this image have a newer tag published" and "does this image
have a KNOWN CVE" are independent questions — a newer tag doesn't imply
it fixes anything, and this check's own answer is useful even for an
image with zero current CVE findings — so it now runs (and can be
skipped/run standalone via --skip=image-upgrades/--include=image-upgrades)
on its own.

One registry tag-list call per unique (repository, version) pin — cheap,
no image pull — but still worth caching: results are cached by
(repository, version) in <repo-root>/.cache/image-upgrade-cache.json
(see lib.image.upgrade_cache — split into its own module so lib.checks.cve
can read this cache too, read-only, to annotate a CVE finding as
"upgradable" without triggering a registry call of its own), a personal,
gitignored, per-checkout cache (same as <repo-root>/.cache/
cve-scan-cache.json — see lib.checks.cve's docstring), not shared between
contributors or CI. image_upgrade_check.tag_check_cache_ttl_days (lib.
settings) is deliberately much shorter than the CVE cache's TTL: a new
tag can be published at any
moment, so "no newer tag as of yesterday" is a far weaker guarantee than
"no new CVE disclosed against this exact, unchanged digest last week" —
caching here is purely about not re-querying every registry on every
single local run within the same day, not about the answer being stable
over any longer window.

Never fails regardless of findings — a newer tag being published is
advisory (worth checking whether it's worth bumping to), not something
this repo's own content violates."""

import urllib.error

from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from pathlib import Path

from lib.checks.cve import bucket_of
from lib.checks.cve import classify_by_key
from lib.checks.cve import dependency_names
from lib.checks.cve import render_image_labels
from lib.checks.cve import top_level_key_for_line
from lib.image.digests import unique_digest_pin_targets
from lib.image.upgrade_cache import cache_entry_is_fresh
from lib.image.upgrade_cache import cache_key
from lib.image.upgrade_cache import load_cache
from lib.image.upgrade_cache import save_cache
from lib.registry import find_newest_same_variant_tag
from lib.registry import parse_repo
from lib.render_scope import friendly_vendor_charts
from lib.render_scope import render_chart
from lib.settings import image_upgrade_tag_check_cache_ttl_days


@dataclass
class UpgradeCheckContext:
    """Everything _resolve_target_upgrade needs to resolve ONE digest-pin
    target that doesn't vary per-target: the label lookups it falls back
    through (rendered_labels/values_lines/dep_names/vendor_map) and the
    cache state that stays fixed while the scan is in progress
    (old_cache, ttl_days). See check_image_upgrades, which builds this."""

    rendered_labels: dict
    values_lines: list
    dep_names: object
    vendor_map: dict
    old_cache: dict
    ttl_days: int


@dataclass
class ImageUpgradeScan:
    """Everything check_image_upgrades's own print/detail logic needs from
    a completed registry-check pass: the per-ref info map, the three
    own/partner-vendor/other-vendor ref buckets, and the fetch-errors/
    cache-hits scan stats. See _scan_image_upgrades, which builds this."""

    images: dict
    own_refs: list
    partner_refs: list
    other_refs: list
    fetch_errors: list
    cache_hits: int


def _upgrade_info(label: str, newest: str, version: str):
    """One images[] entry: bucket_of(label), a vendor-label suffix (only
    for a partner-vendor image — see check_image_upgrades' docstring for
    why own/other never carry one), and whether a newer tag is published."""
    return {
        "bucket": bucket_of(label),
        "vendor_label": label if bucket_of(label) == "partner" else None,
        "newest": newest,
        "has_newer": newest != version,
    }


def _label_for_target(repository: str, version: str, digest: str, line: int, ctx):
    """Label for one target: the render's own "# Source:" attribution when
    it rendered at all, else the values.yaml top-level-key heuristic (see
    this module's own docstring for why own always wins)."""
    label = ctx.rendered_labels.get((repository, version, digest))
    if label is not None:
        return label
    top_key = top_level_key_for_line(ctx.values_lines, line)
    return classify_by_key(top_key, ctx.dep_names, ctx.vendor_map)


@dataclass
class _TargetResolveInfo:
    """A target's own fixed identity, resolved once up front and threaded
    through both the cache-hit and registry-fetch paths of
    _resolve_target_upgrade — see that function."""

    image_ref: str
    key: str
    host: str
    repo_path: str
    version: str
    label: str


@dataclass
class _TargetResult:
    """One target's outcome, as returned by _resolve_target_upgrade: on a
    registry fetch failure, only image_ref and error=True are meaningful;
    otherwise key/cache_entry/info are this target's tag-cache entry and
    images[] entry, and cache_hit says whether it came from the cache."""

    image_ref: str
    key: object = None
    cache_entry: object = None
    info: object = None
    cache_hit: bool = False
    error: bool = False


def _fetch_target_upgrade(i: int, total: int, info):
    """The registry-fetch path of _resolve_target_upgrade: announces the
    real tag-list call (a cache hit is near-instant and stays silent —
    same convention as check_cves), then queries the registry."""
    print(f"  [{i}/{total}] checking {info.image_ref} for a newer tag...", flush=True)
    try:
        newest = find_newest_same_variant_tag(info.host, info.repo_path, info.version)
    except (urllib.error.URLError, OSError) as e:
        print(f"  [FETCH-ERR] {info.image_ref}  {e}")
        return _TargetResult(info.image_ref, error=True)

    cache_entry = {"checked_at": datetime.now(timezone.utc).isoformat(), "newest": newest}
    return _TargetResult(info.image_ref, info.key, cache_entry, _upgrade_info(info.label, newest, info.version))


def _resolve_target_upgrade(i: int, total: int, target: tuple, ctx):
    """Resolves ONE unique_digest_pin_targets entry against the tag cache
    (a fresh cache hit) or the registry (see _fetch_target_upgrade)."""
    (repository, version), (digest, line) = target
    host, repo_path = parse_repo(repository)
    info = _TargetResolveInfo(
        f"{host}/{repo_path}:{version}",
        cache_key(repository, version),
        host,
        repo_path,
        version,
        _label_for_target(repository, version, digest, line, ctx),
    )
    cached = ctx.old_cache.get(info.key)

    if cached and cache_entry_is_fresh(cached, ctx.ttl_days):
        result_info = _upgrade_info(info.label, cached["newest"], info.version)
        return _TargetResult(info.image_ref, info.key, cached, result_info, cache_hit=True)

    return _fetch_target_upgrade(i, total, info)


def _bucket_refs(images: dict):
    """own_refs, partner_refs, other_refs -- the ref lists for each of
    check_image_upgrades' own/partner-vendor/other-vendor buckets, drawn
    from `images`' own "bucket" field (see _upgrade_info)."""

    def refs_in(bucket: str):
        return [ref for ref, info in images.items() if info["bucket"] == bucket]

    return refs_in("own"), refs_in("partner"), refs_in("other")


def _scan_image_upgrades(chart_dir: Path, targets: list, ctx):
    """Resolves every target (see _resolve_target_upgrade), saving the tag
    cache incrementally after each real registry call (same convention as
    check_cves) and once more at the end (to drop stale entries for an
    image no longer pinned). Bundles the result into an ImageUpgradeScan."""
    new_cache = {}
    cache_hits = 0
    images = {}
    fetch_errors = []

    for i, target in enumerate(targets, 1):
        r = _resolve_target_upgrade(i, len(targets), target, ctx)
        if r.error:
            fetch_errors.append(r.image_ref)
            continue
        new_cache[r.key] = r.cache_entry
        if r.cache_hit:
            cache_hits += 1
        else:
            save_cache(chart_dir, new_cache)  # persist incrementally, same as check_cves
        images[r.image_ref] = r.info

    save_cache(chart_dir, new_cache)  # drop entries for images no longer pinned

    own_refs, partner_refs, other_refs = _bucket_refs(images)
    return ImageUpgradeScan(images, own_refs, partner_refs, other_refs, fetch_errors, cache_hits)


def _print_image_upgrade_findings(scan, total: int, ttl_days: int):
    """Prints check_image_upgrades' three report sections (own/partner-
    vendor/other-vendor), the OK-line/fetch-errors sections, and the
    cache-hit summary line -- see check_image_upgrades' own docstring for
    what each section means."""
    print_upgradable("Own images", scan.own_refs, scan.images)
    print_upgradable("Partner-vendor images", scan.partner_refs, scan.images)
    print_upgradable("Other-vendor images", scan.other_refs, scan.images)

    if not any(info["has_newer"] for info in scan.images.values()):
        print("OK: no newer tag published for any pinned image")

    if scan.fetch_errors:
        print(f"{len(scan.fetch_errors)} image(s) could not be checked:")
        for ref in scan.fetch_errors:
            print(f"  {ref}")
    print(f"{scan.cache_hits}/{total} image(s) served from cache (checked within the last {ttl_days} day(s))")


def _image_upgrade_detail(scan):
    own_n, own_up = bucket_totals(scan.own_refs, scan.images)
    partner_n, partner_up = bucket_totals(scan.partner_refs, scan.images)
    other_n, other_up = bucket_totals(scan.other_refs, scan.images)
    return (
        f"upgradable: {own_up}/{own_n} own, {partner_up}/{partner_n} partner-vendor, "
        f"{other_up}/{other_n} other-vendor; {len(scan.fetch_errors)} fetch error(s)"
    )


def check_image_upgrades(chart_dir: Path, extra_args: list):
    """The verify-podiumd check itself: for every unique digest-pinned
    image in values.yaml, ask the registry (via find_newest_same_variant_
    tag, cached per (repository, version) — see lib.image.upgrade_cache)
    whether a numerically-newer same-variant tag is currently published,
    then print the own/partner-vendor/other-vendor upgradable buckets
    (see this module's own docstring for the full bucket/caching
    rationale). Always returns (True, detail) — a newer tag being
    published never fails this check, only informs it; `detail` is the
    one-line "upgradable: X/Y own, ..." summary. Returns (False, "helm
    template failed to render") only if the render itself fails, before
    any registry call is made."""
    ttl_days = image_upgrade_tag_check_cache_ttl_days(chart_dir)

    result = render_chart(chart_dir, extra_args)
    if result.returncode != 0:
        return False, "helm template failed to render"

    vendor_map = friendly_vendor_charts(chart_dir)
    dep_names = dependency_names(chart_dir)
    rendered_labels = render_image_labels(result.stdout, vendor_map)

    values_path = chart_dir / "values.yaml"
    values_lines = values_path.read_text(encoding="utf-8").splitlines()
    targets = sorted(unique_digest_pin_targets(values_lines).items())

    ctx = UpgradeCheckContext(rendered_labels, values_lines, dep_names, vendor_map, load_cache(chart_dir), ttl_days)
    print(f"Checking {len(targets)} unique pinned image(s) for a newer published tag...")
    scan = _scan_image_upgrades(chart_dir, targets, ctx)

    _print_image_upgrade_findings(scan, len(targets), ttl_days)
    return True, _image_upgrade_detail(scan)


def bucket_totals(refs: list, images: dict):
    """(total, upgradable_count) for `refs` (one bucket's image refs) against
    `images` (check_image_upgrades's own ref -> info map) — feeds the
    final "upgradable: X/Y own, ..." summary line."""
    return len(refs), sum(1 for ref in refs if images[ref]["has_newer"])


def print_upgradable(title: str, refs: list, images: dict):
    """Print `title` as a section heading followed by one line per ref in
    `refs` that has a newer tag available (images[ref]["has_newer"]),
    each with its vendor label suffix when the image has one (see
    check_image_upgrades) — silently prints nothing at all if no ref in
    this bucket is upgradable, so a clean bucket never adds an empty
    heading to the report."""
    upgradable = [ref for ref in refs if images[ref]["has_newer"]]
    if not upgradable:
        return
    print(f"--- {title} ---")
    for ref in upgradable:
        info = images[ref]
        vendor = f" [{info['vendor_label']}]" if info["vendor_label"] else ""
        print(f"{ref}{vendor}: newer tag available: {info['newest']}")
