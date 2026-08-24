"""Report-only check for whether a numerically-newer same-variant tag is
currently published for every unique digest-pinned image in values.yaml,
split into the same own/partner-vendor/other-vendor buckets as
check_yamllint/check_kubeconform/check_shellcheck/check_kube_score/
check_cves. Classification itself is reused directly from lib.cve_check
(own always wins from the `helm template` render's "# Source:"
attribution, falling back to a values.yaml top-level-key heuristic for a
component not present in the render at all — see that module's docstring
for the full rationale). Own AND partner-vendor images are itemized (only
the ones with an upgrade available — nothing to say about a clean image);
other-vendor gets one aggregate rollup line, same convention as everywhere
else this scope split is used — and, like every bucket here, only printed
at all when at least one of its images has an upgrade available. Prints an
explicit "OK" line only when NOTHING anywhere is upgradeable; per-bucket
totals (upgradeable/total, including clean images) are always in the
one-line summary regardless.

Split out of check_cves, where this used to live folded into its summary
line: "does this image have a newer tag published" and "does this image
have a KNOWN CVE" are independent questions — a newer tag doesn't imply
it fixes anything, and this check's own answer is useful even for an
image with zero current CVE findings — so it now runs (and can be
skipped/run standalone via --skip-image-upgrades/--only-image-upgrades)
on its own.

One registry tag-list call per unique (repository, version) pin — cheap,
no image pull — but still worth caching: results are cached by
(repository, version) in charts/podiumd/image-upgrade-cache.json,
deliberately tracked chart content (same rationale as
charts/podiumd/cve-scan-cache.json — see lib.cve_check's docstring), NOT
gitignored, so the cache travels with whatever branch/checkout someone is
on and other contributors/CI don't re-query every registry on every run.
IMAGE_UPGRADE_CACHE_TTL_DAYS is deliberately much shorter than the CVE
cache's TTL: a new tag can be published at any moment, so "no newer tag
as of yesterday" is a far weaker guarantee than "no new CVE disclosed
against this exact, unchanged digest last week" — caching here is purely
about not re-querying every registry on every single local run within the
same day, not about the answer being stable over any longer window.

Never fails regardless of findings — a newer tag being published is
advisory (worth checking whether it's worth bumping to), not something
this repo's own content violates."""
import json
import urllib.error
from datetime import datetime, timedelta, timezone

from lib.cve_check import bucket_of, classify_by_key, dependency_names, render_image_labels, top_level_key_for_line
from lib.image_digests import scan_digest_pins
from lib.procutil import run
from lib.registry import find_newest_same_variant_tag, parse_repo
from lib.render_scope import CHART_NAME, friendly_vendor_charts, supports_skip_schema_validation

CACHE_FILENAME = "image-upgrade-cache.json"

# Much shorter than cve_check's CVE_CACHE_TTL_DAYS — see module docstring.
IMAGE_UPGRADE_CACHE_TTL_DAYS = 1


def cache_path(chart_dir):
    """charts/podiumd/image-upgrade-cache.json — tracked chart content (see
    module docstring), not gitignored."""
    return chart_dir / CACHE_FILENAME


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


def check_image_upgrades(chart_dir, extra_args):
    template_args = list(extra_args)
    if supports_skip_schema_validation():
        template_args.append("--skip-schema-validation")

    result = run(["helm", "template", CHART_NAME, str(chart_dir), *template_args],
                 capture_output=True, text=True)
    if result.returncode != 0:
        return False, "helm template failed to render"

    vendor_map = friendly_vendor_charts(chart_dir)
    dep_names = dependency_names(chart_dir)
    rendered_labels = render_image_labels(result.stdout, vendor_map)

    values_path = chart_dir / "values.yaml"
    values_lines = values_path.read_text(encoding="utf-8").splitlines()
    pins = scan_digest_pins(values_lines)

    # First (digest, line) seen per (repository, version) — same convention
    # as check_image_digests/check_cves.
    targets = {}
    for p in pins:
        if p["repository"]:
            targets.setdefault((p["repository"], p["version"]), (p["digest"], p["line"]))
    targets = sorted(targets.items())

    old_cache = load_cache(chart_dir)
    new_cache = {}
    cache_hits = 0

    print(f"Checking {len(targets)} unique pinned image(s) for a newer published tag...")

    images = {}
    fetch_errors = []
    for (repository, version), (digest, line) in targets:
        host, repo_path = parse_repo(repository)
        image_ref = f"{host}/{repo_path}:{version}"
        key = cache_key(repository, version)
        cached = old_cache.get(key)

        label = rendered_labels.get((repository, version, digest))
        if label is None:
            top_key = top_level_key_for_line(values_lines, line)
            label = classify_by_key(top_key, dep_names, vendor_map)

        if cached and cache_entry_is_fresh(cached):
            newest = cached["newest"]
            cache_hits += 1
            new_cache[key] = cached
        else:
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

    print_upgradeable("Own images", own_refs, images)
    print_upgradeable("Partner-vendor images", partner_refs, images)
    print_aggregate("Other-vendor images", other_refs, images)

    if not any(info["has_newer"] for info in images.values()):
        print("OK: no newer tag published for any pinned image")

    if fetch_errors:
        print(f"{len(fetch_errors)} image(s) could not be checked: {', '.join(fetch_errors)}")
    print(f"{cache_hits}/{len(targets)} image(s) served from cache (checked within the last "
          f"{IMAGE_UPGRADE_CACHE_TTL_DAYS} day(s))")

    if new_cache != old_cache:
        print(f"{cache_path(chart_dir)} changed — commit it so other contributors and CI "
              f"don't re-check these same images today.")

    own_n, own_up = bucket_totals(own_refs, images)
    partner_n, partner_up = bucket_totals(partner_refs, images)
    other_n, other_up = bucket_totals(other_refs, images)
    detail = (f"{own_up}/{own_n} own upgradeable, {partner_up}/{partner_n} partner-vendor upgradeable, "
              f"{other_up}/{other_n} other-vendor upgradeable, {len(fetch_errors)} fetch error(s)")
    return True, detail


def bucket_totals(refs, images):
    return len(refs), sum(1 for ref in refs if images[ref]["has_newer"])


def print_upgradeable(title, refs, images):
    upgradeable = [ref for ref in refs if images[ref]["has_newer"]]
    if not upgradeable:
        return
    print(f"--- {title} ---")
    for ref in upgradeable:
        info = images[ref]
        vendor = f" [{info['vendor_label']}]" if info["vendor_label"] else ""
        print(f"{ref}{vendor}: newer tag available: {info['newest']}")


def print_aggregate(title, refs, images):
    upgradeable = sum(1 for ref in refs if images[ref]["has_newer"])
    if not upgradeable:
        return
    print(f"--- {title} ---")
    print(f"  {upgradeable}/{len(refs)} image(s) have a newer tag published")
