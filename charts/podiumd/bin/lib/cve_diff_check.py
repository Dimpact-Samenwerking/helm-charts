"""Report-only check: for every image check_image_upgrades flagged with a
newer tag published, or check_image_digests flagged with a slid digest,
scan BOTH the currently-pinned image and the proposed replacement with
trivy (lib.cve_check.run_trivy) and report the per-severity CVE SET
DIFFERENCE — which CVEs the proposed image closes (present now, absent
after) and which it newly introduces (absent now, present after). An
upgrade/re-pin decision informed by real security data, not just "a newer
tag/digest exists" (which lib.image_upgrade_check/lib.image_digests
already report on their own, with no opinion on whether it actually fixes
anything).

Deliberately a SEPARATE step from both of those (cheap, network-only, no
docker) and from check_cves itself (which scans every currently-pinned
image once, not a proposed replacement) — bolting a second per-candidate
docker+trivy cost onto a cheap step would recreate the exact cost-tier
mismatch this repo already found and fixed once for check_digest_pinning/
check_shared_image_usage (see lib.digest_pinning_check's own module
docstring). Cost here is still bounded: only images with an ACTUAL
flagged upgrade or slide get a second scan, not every pinned image, so
this runs by default like every other step — no separate opt-in flag,
unlike check_cves' own --detail-cve-check.

Never fails, same "a triage decision for a human, not a chart-correctness
fact" precedent check_cves itself already established — a proposed image
introducing a new CRITICAL is worth knowing before bumping, not a reason
to make verify-podiumd itself red.

Candidates, gathered from two independent sources:
- "upgrade" — every unique digest pin (lib.image_digests.
  unique_digest_pin_targets, the same simple "no subchart-default
  fallback" resolution check_image_upgrades/check_cves already use) with
  a fresh lib.image_upgrade_cache entry showing a newer tag than the one
  currently pinned. current_ref is the plain pinned tag
  ("host/repo:version"); proposed_ref is that same repo at the newer tag.
  Reading image_upgrade_cache read-only here (same as check_cves' own
  "upgradable to X" annotation) is why "CVE diff" lists "Image upgrades"
  as a STEP_PREREQUISITES entry — a bare --include=cve-diff still needs
  that cache freshly populated first.
- "sliding digest" — every pin lib.image_digests.find_sliding_pins
  reports (the exact same registry lookup check_image_digests' own loop
  uses, factored out there so it isn't re-derived here — see that
  function's own docstring). current_ref MUST be digest-pinned
  ("repo@sha256:<pinned_digest>"), never the bare tag: the tag alone
  would now resolve to the NEW upstream digest, not what's actually
  pinned in values.yaml. proposed_ref is the same repo at the new
  upstream digest — deliberately digest-pinned too (not the bare tag),
  so this scan is reproducible regardless of whatever the tag resolves
  to by the time this step actually runs.

The two sources are independent and never deduplicated against each
other: a pin that happens to be BOTH sliding AND upgradable is reported
twice, once under each heading — a rare enough overlap in practice that
merging the two into one combined diff isn't worth the added complexity
it would take to do correctly.

Caching: BOTH sides of each candidate reuse lib.cve_check's own
digest-keyed cve-scan-cache.json directly (same cache_key/load_cache/
save_cache/cache_entry_is_fresh check_cves itself uses) — but the two
sides, and the two candidate KINDS, get there differently:
- The CURRENT side is always cache-eligible immediately: its digest is
  already known from values.yaml, and check_cves (which runs
  immediately before this step in the default pipeline) already scanned
  every currently-pinned image, so this side is typically a free cache
  hit, not a second docker pull.
- A "sliding digest" candidate's PROPOSED side is ALSO free: find_
  sliding_pins already resolved the new upstream digest itself (a
  registry call check_image_digests' own work already made, not a new
  one this module triggers) — see gather_candidates' own
  "proposed_digest" field.
- An "upgrade" candidate's PROPOSED side is a bare TAG (lib.
  image_upgrade_check never records the digest, only the tag string) —
  its digest genuinely isn't known ahead of time, so caching it costs
  ONE extra registry_tag_exists manifest lookup (a cheap tag->digest
  resolve, NOT a docker pull) before the scan. If that resolve call
  itself fails, this candidate's proposed side just falls back to an
  uncached run_trivy — never treated as a scan failure on its own, the
  same tolerance the tag-check that produced the candidate in the first
  place already has for its own failed lookups."""
import urllib.error
from collections import Counter
from datetime import datetime, timezone

from lib.cve_check import (
    HIGH_SEVERITIES, SEVERITY_ORDER, cache_entry_is_fresh, cache_key, high_findings_by_package, load_cache,
    print_package_line, run_trivy, save_cache, severity_label,
)
from lib.image_digests import find_sliding_pins, unique_digest_pin_targets
from lib.image_upgrade_cache import cache_entry_is_fresh as upgrade_entry_is_fresh
from lib.image_upgrade_cache import cache_key as upgrade_cache_key
from lib.image_upgrade_cache import load_cache as load_upgrade_cache
from lib.registry import parse_repo, registry_tag_exists


def _vuln_key(v):
    return (v["VulnerabilityID"], v["PkgName"])


def diff_vulns(current_vulns, proposed_vulns):
    """(closed, introduced) — lists of vuln dicts (same shape lib.
    cve_check.run_trivy returns) present in exactly one side, keyed by
    the exact (VulnerabilityID, PkgName) pair. An EXACT set difference,
    never a naive per-severity count subtraction — that would hide e.g.
    "5 closed, 3 newly introduced" behind a misleading "net -2"."""
    current_by_key = {_vuln_key(v): v for v in current_vulns}
    proposed_by_key = {_vuln_key(v): v for v in proposed_vulns}
    closed = [v for key, v in current_by_key.items() if key not in proposed_by_key]
    introduced = [v for key, v in proposed_by_key.items() if key not in current_by_key]
    return closed, introduced


def _bare_digest(digest_ref):
    """"sha256:<hex>" -> "<hex>" — lib.cve_check.cache_key expects the
    bare hex digest (it prepends "sha256:" itself), but every digest this
    module gets handed back (find_sliding_pins, registry_tag_exists) has
    the full "sha256:" prefix already on it."""
    prefix = "sha256:"
    return digest_ref[len(prefix):] if digest_ref.startswith(prefix) else digest_ref


def gather_candidates(chart_dir):
    """[{"kind", "repository", "version", "current_ref", "current_digest",
    "proposed_label", "proposed_ref", "proposed_digest"}] — see this
    module's own docstring for exactly what each of the two candidate
    sources means and why each ref is built the way it is.

    "proposed_digest" is the one field that genuinely differs by kind:
    a "sliding digest" candidate's new upstream digest is already known
    (find_sliding_pins' own registry lookup resolved it), set here
    directly, no extra call. An "upgrade" candidate's proposed side is
    only ever a bare TAG (lib.image_upgrade_check never records a
    digest) — left None here, resolved lazily by _scan_proposed only if
    the candidate actually needs scanning."""
    values_path = chart_dir / "values.yaml"
    values_lines = values_path.read_text(encoding="utf-8").splitlines()
    targets = unique_digest_pin_targets(values_lines)

    upgrade_cache = load_upgrade_cache(chart_dir)
    candidates = []
    for (repository, version), (digest, _line) in sorted(targets.items()):
        entry = upgrade_cache.get(upgrade_cache_key(repository, version))
        if entry and upgrade_entry_is_fresh(entry) and entry["newest"] != version:
            host, repo_path = parse_repo(repository)
            candidates.append({
                "kind": "upgrade",
                "repository": repository,
                "version": version,
                "current_ref": f"{host}/{repo_path}:{version}",
                "current_digest": digest,
                "proposed_label": entry["newest"],
                "proposed_ref": f"{host}/{repo_path}:{entry['newest']}",
                "proposed_digest": None,
            })

    for repository, version, pinned_digest, digest in find_sliding_pins(chart_dir):
        candidates.append({
            "kind": "sliding digest",
            "repository": repository,
            "version": version,
            "current_ref": f"{repository}@sha256:{pinned_digest}",
            "current_digest": pinned_digest,
            "proposed_label": digest,
            "proposed_ref": f"{repository}@{digest}",
            "proposed_digest": _bare_digest(digest),
        })

    return candidates


def _scan_cached(chart_dir, repository, digest, ref, old_cache, new_cache):
    """Scan `ref` via trivy, reusing lib.cve_check's own digest-keyed
    cve-scan-cache.json whenever `digest` (bare hex, see _bare_digest) is
    known — shared by _scan_current (always has one) and _scan_proposed
    (only sometimes does, see its own docstring). `digest=None` skips the
    cache entirely, straight through to run_trivy — used when a proposed
    tag's digest couldn't be resolved. Returns None if trivy's own scan
    failed or produced unparseable output."""
    key = cache_key(repository, digest) if digest is not None else None
    if key is not None:
        cached = old_cache.get(key)
        if cached and cache_entry_is_fresh(cached):
            new_cache[key] = cached
            return cached["vulnerabilities"]

    vulns = run_trivy(ref)
    if vulns is None:
        return None

    if key is not None:
        new_cache[key] = {"scanned_at": datetime.now(timezone.utc).isoformat(), "vulnerabilities": vulns}
        save_cache(chart_dir, new_cache)
    return vulns


def _scan_current(chart_dir, candidate, old_cache, new_cache):
    """The CURRENT side of one candidate — always cache-eligible, its
    pinned digest is already known from values.yaml (see _scan_cached),
    a free hit whenever check_cves already scanned this exact digest."""
    return _scan_cached(chart_dir, candidate["repository"], candidate["current_digest"],
                         candidate["current_ref"], old_cache, new_cache)


def _scan_proposed(chart_dir, candidate, old_cache, new_cache):
    """The PROPOSED side of one candidate. A "sliding digest" candidate
    already carries its own resolved digest (see gather_candidates) — no
    extra call needed, straight to _scan_cached. An "upgrade" candidate's
    own proposed_ref is a bare tag — resolve its digest first via ONE
    cheap registry_tag_exists manifest lookup (not a docker pull) so it
    can join the same cache. If that resolve call itself fails/errors,
    fall back to an uncached scan (digest=None) rather than treating the
    whole candidate as a failure — the tag-check that produced this
    candidate in the first place already tolerates the same kind of
    lookup failure without giving up on the candidate outright."""
    digest = candidate["proposed_digest"]
    if digest is None:
        host, repo_path = parse_repo(candidate["repository"])
        try:
            exists, resolved = registry_tag_exists(host, repo_path, candidate["proposed_label"])
            if exists and resolved:
                digest = _bare_digest(resolved)
        except (urllib.error.URLError, OSError):
            digest = None

    return _scan_cached(chart_dir, candidate["repository"], digest, candidate["proposed_ref"],
                         old_cache, new_cache)


def _severity_counts(vulns):
    counts = Counter(v["Severity"] for v in vulns)
    return ", ".join(f"{counts[s]} {severity_label(s)}" for s in SEVERITY_ORDER if counts.get(s))


def _print_direction(label, vulns, detail):
    if not vulns:
        print(f"  {label}: none")
        return
    print(f"  {label}: {_severity_counts(vulns)}")
    if detail:
        high_vulns = [v for v in vulns if v["Severity"] in HIGH_SEVERITIES]
        for pkg, vulns_for_pkg in sorted(high_findings_by_package(high_vulns).items()):
            print_package_line(pkg, vulns_for_pkg)


def print_candidate_report(candidate, closed, introduced, detail):
    print(f"{candidate['repository']}: {candidate['version']} -> {candidate['proposed_label']}  "
          f"[{candidate['kind']}]")
    _print_direction("closed", closed, detail)
    _print_direction("introduced", introduced, detail)
    print()


def check_cve_diff(chart_dir, extra_args, detail=False):
    candidates = gather_candidates(chart_dir)

    if not candidates:
        print("OK: no upgrade-available or sliding-digest candidate to diff")
        return True, "0 candidate(s)"

    print(f"Diffing CVEs for {len(candidates)} upgrade/slide candidate(s) (current vs proposed, "
          f"via trivy)...")

    old_cache = load_cache(chart_dir)
    new_cache = dict(old_cache)
    total_closed = 0
    total_introduced = 0
    scan_errors = []

    for i, candidate in enumerate(candidates, 1):
        current_vulns = _scan_current(chart_dir, candidate, old_cache, new_cache)
        if current_vulns is None:
            scan_errors.append(candidate["current_ref"])
            print(f"  [SCAN-ERR] {candidate['current_ref']}  trivy scan failed or produced "
                  f"unparseable output")
            continue

        print(f"  [{i}/{len(candidates)}] scanning proposed {candidate['proposed_ref']} "
              f"(docker pull + trivy, unless cached)...", flush=True)
        proposed_vulns = _scan_proposed(chart_dir, candidate, old_cache, new_cache)
        if proposed_vulns is None:
            scan_errors.append(candidate["proposed_ref"])
            print(f"  [SCAN-ERR] {candidate['proposed_ref']}  trivy scan failed or produced "
                  f"unparseable output")
            continue

        closed, introduced = diff_vulns(current_vulns, proposed_vulns)
        total_closed += len(closed)
        total_introduced += len(introduced)
        print_candidate_report(candidate, closed, introduced, detail)

    save_cache(chart_dir, new_cache)

    if scan_errors:
        print(f"{len(scan_errors)} image(s) could not be scanned:")
        for ref in scan_errors:
            print(f"  {ref}")

    detail_msg = (f"{len(candidates)} candidate(s) diffed: {total_closed} CVE(s) closed overall, "
                  f"{total_introduced} newly introduced; {len(scan_errors)} scan error(s)")
    return True, detail_msg
