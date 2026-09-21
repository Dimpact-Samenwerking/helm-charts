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
from datetime import datetime, timezone

from lib.checks.cve import bucket_of, classify_by_key, dependency_names, render_image_labels, top_level_key_for_line
from lib.image.digests import unique_digest_pin_targets
from lib.image.upgrade_cache import cache_entry_is_fresh, cache_key, load_cache, save_cache
from lib.registry import find_newest_same_variant_tag, parse_repo
from lib.render_scope import friendly_vendor_charts, render_chart
from lib.settings import image_upgrade_tag_check_cache_ttl_days


def check_image_upgrades(chart_dir, extra_args):
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

    old_cache = load_cache(chart_dir)
    new_cache = {}
    cache_hits = 0

    print(f"Checking {len(targets)} unique pinned image(s) for a newer published tag...")

    images = {}
    fetch_errors = []
    for i, ((repository, version), (digest, line)) in enumerate(targets, 1):
        host, repo_path = parse_repo(repository)
        image_ref = f"{host}/{repo_path}:{version}"
        key = cache_key(repository, version)
        cached = old_cache.get(key)

        label = rendered_labels.get((repository, version, digest))
        if label is None:
            top_key = top_level_key_for_line(values_lines, line)
            label = classify_by_key(top_key, dep_names, vendor_map)

        if cached and cache_entry_is_fresh(cached, ttl_days):
            newest = cached["newest"]
            cache_hits += 1
            new_cache[key] = cached
        else:
            # A cache hit is near-instant and stays silent (same
            # convention as check_cves — only totaled in the final
            # "N/M served from cache" line); a real tag-list call is the
            # one thing here worth announcing as it starts.
            print(f"  [{i}/{len(targets)}] checking {image_ref} for a newer tag...", flush=True)
            try:
                newest = find_newest_same_variant_tag(host, repo_path, version)
            except (urllib.error.URLError, OSError) as e:
                fetch_errors.append(image_ref)
                print(f"  [FETCH-ERR] {image_ref}  {e}")
                continue
            new_cache[key] = {
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "newest": newest,
            }
            save_cache(chart_dir, new_cache)  # persist incrementally, same as check_cves

        images[image_ref] = {
            "bucket": bucket_of(label),
            "vendor_label": label if bucket_of(label) == "partner" else None,
            "newest": newest,
            "has_newer": newest != version,
        }

    save_cache(chart_dir, new_cache)  # drop entries for images no longer pinned

    def refs_in(bucket):
        return [ref for ref, info in images.items() if info["bucket"] == bucket]

    own_refs, partner_refs, other_refs = refs_in("own"), refs_in("partner"), refs_in("other")

    print_upgradable("Own images", own_refs, images)
    print_upgradable("Partner-vendor images", partner_refs, images)
    print_upgradable("Other-vendor images", other_refs, images)

    if not any(info["has_newer"] for info in images.values()):
        print("OK: no newer tag published for any pinned image")

    if fetch_errors:
        print(f"{len(fetch_errors)} image(s) could not be checked:")
        for ref in fetch_errors:
            print(f"  {ref}")
    print(f"{cache_hits}/{len(targets)} image(s) served from cache (checked within the last {ttl_days} day(s))")

    own_n, own_up = bucket_totals(own_refs, images)
    partner_n, partner_up = bucket_totals(partner_refs, images)
    other_n, other_up = bucket_totals(other_refs, images)
    detail = (
        f"upgradable: {own_up}/{own_n} own, {partner_up}/{partner_n} partner-vendor, "
        f"{other_up}/{other_n} other-vendor; {len(fetch_errors)} fetch error(s)"
    )
    return True, detail


def bucket_totals(refs, images):
    return len(refs), sum(1 for ref in refs if images[ref]["has_newer"])


def print_upgradable(title, refs, images):
    upgradable = [ref for ref in refs if images[ref]["has_newer"]]
    if not upgradable:
        return
    print(f"--- {title} ---")
    for ref in upgradable:
        info = images[ref]
        vendor = f" [{info['vendor_label']}]" if info["vendor_label"] else ""
        print(f"{ref}{vendor}: newer tag available: {info['newest']}")
