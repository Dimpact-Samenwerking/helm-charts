#!/usr/bin/env python3
"""
Refresh stale digest pins in charts/podiumd/values.yaml.

"Stale" here means the version tag (e.g. "1.31.3") is unchanged, but
upstream re-published that tag with new base/security layers, so the
multi-arch index digest changed. The old pinned digest is still pullable
(it's immutable) — nothing is broken — but the deployment runs old layers
and misses upstream patches.

For each unique "<repository>:<tag>" pin found in values.yaml, fetches the
live "Docker-Content-Digest" from the upstream registry and, if it differs
from the pinned digest, replaces every occurrence of the old 64-hex digest
with the new one — byte-identical otherwise (tag, quoting, comments
untouched). A single image (e.g. nginx-unprivileged) can be pinned many
times; all occurrences are updated together since they share the exact
same old digest string.

A tag known to slide is treated differently: its digest is EXPECTED to
drift as upstream re-publishes the tag, so by default it's reported but
left untouched, not rewritten. "Known to slide" means either this repo's
own git history shows the tag has changed digest before (direct proof), or
— only when that's inconclusive — the registry currently has a more
specific sibling tag at the same digest (e.g. "3.14.7-slim" alongside our
"3.14-slim", both at the same digest right now). Everything else is
treated as a component's own release tag, which should never legitimately
change once published — by default that's the only kind this script
updates. Pass --all to also update sliding pins.

Pins with no discoverable repository (no active "repository:" sibling key,
no "# host/repo:tag" reference comment, no commented-out "#repository:"
hint) are reported and left untouched — this happens for the handful of
images that rely entirely on their sub-chart's own default repository.

This never touches tag-only image refs that have no "@sha256:..." pin
(e.g. an apisix default) — those aren't pinned in values.yaml at all and
belong in the release's docs/images/images-<version>.yaml instead.

Usage:
    set-image-digests.py             # fetch, compare, rewrite stale PINNED digests only
    set-image-digests.py --all       # also rewrite stale SLIDING digests
    set-image-digests.py --dry-run   # fetch and compare only, no write (combine with --all as needed)

After a real run, re-render the chart (verify-podiumd.py or
/helm-render-all) to confirm the new digests are picked up cleanly.
"""
import re
import sys
import urllib.error
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from lib.registry import is_sliding_tag, parse_repo, registry_tag_exists

VALUES_PATH = SCRIPT_DIR.parents[0] / "values.yaml"

DIGEST_PIN_RE = re.compile(
    r'^(?P<indent>\s*)tag:\s*"?(?P<version>[\w][\w.\-]*)@sha256:(?P<digest>[0-9a-f]{64})"?\s*(?:#.*)?$'
)
ACTIVE_REPO_RE = re.compile(
    r'^(?P<indent>\s*)repository:\s*"?(?P<repo>[\w][\w.\-]*(?:/[\w.\-]+)*)"?\s*(?:#.*)?$'
)
COMMENTED_REPO_RE = re.compile(
    r'^\s*#\s*repository:\s*"?(?P<repo>[\w][\w.\-]*(?:/[\w.\-]+)*)"?\s*$'
)
REF_COMMENT_RE = re.compile(
    r'^\s*#\s*(?P<repo>[a-zA-Z0-9][\w.\-]*(?:/[\w.\-]+)*):@?[\w][\w.\-]*(?:@sha256:[0-9a-f]{64})?\s*$'
)


def resolve_pin_repo(lines, tag_line_index, tag_indent):
    """Resolve the upstream repository for a "tag:" pin at tag_line_index.
    Most pins have an active sibling "repository:" key. A minority of
    components (e.g. office_converter, opa, solr-operator) deliberately
    comment their "repository:" out so gemeente-level ACR-mirror overrides
    take precedence — for those, fall back to the "# host/repo:tag" style
    reference comment placed above the "image:" block, or a commented-out
    "#repository: <value>" key at the same indent."""
    for i in range(tag_line_index - 1, max(tag_line_index - 15, -1), -1):
        raw = lines[i]
        if not raw.strip():
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        if indent < tag_indent:
            break
        m = ACTIVE_REPO_RE.match(raw)
        if m and indent == tag_indent:
            return m.group("repo")
    for i in range(tag_line_index - 1, max(tag_line_index - 6, -1), -1):
        m = REF_COMMENT_RE.match(lines[i])
        if m:
            return m.group("repo")
    for i in range(tag_line_index - 1, max(tag_line_index - 6, -1), -1):
        m = COMMENTED_REPO_RE.match(lines[i])
        if m:
            return m.group("repo")
    return None


def scan_digest_pins(lines):
    """Yield one record per "tag: <version>@sha256:<digest>" pin in
    values.yaml, with its resolved upstream repository."""
    pins = []
    for i, raw in enumerate(lines):
        m = DIGEST_PIN_RE.match(raw)
        if not m:
            continue
        indent = len(m.group("indent"))
        pins.append({
            "line": i + 1,
            "version": m.group("version"),
            "digest": m.group("digest"),
            "repository": resolve_pin_repo(lines, i, indent),
        })
    return pins


def find_stale_digests(lines, values_path):
    """Return (stale, unresolved, fetch_errors). stale is a list of
    (repository, version, old_digest, new_digest, [line, ...], sliding) —
    see lib.registry.is_sliding_tag for what makes a mismatch "sliding"
    (expected drift) versus a component's own release tag, which should
    never legitimately change once published."""
    pins = scan_digest_pins(lines)
    unresolved = [p for p in pins if not p["repository"]]

    targets = {}
    for p in pins:
        if p["repository"]:
            targets.setdefault((p["repository"], p["version"]), []).append(p)

    stale = []
    fetch_errors = []
    for (repository, version), group in sorted(targets.items()):
        host, repo_path = parse_repo(repository)
        pinned_digest = group[0]["digest"]
        lines_for_pin = [p["line"] for p in group]

        digest, error = None, None
        for _attempt in range(2):
            try:
                exists, digest = registry_tag_exists(host, repo_path, version)
                error = None if exists else "tag not found upstream"
                break
            except (urllib.error.URLError, OSError) as e:
                error = str(e)

        if error:
            fetch_errors.append((repository, version, error, lines_for_pin))
        elif digest and digest != f"sha256:{pinned_digest}":
            sliding = is_sliding_tag(values_path, host, repo_path, version, digest)
            stale.append((repository, version, pinned_digest, digest, lines_for_pin, sliding))

    return stale, unresolved, fetch_errors


def main():
    dry_run = "--dry-run" in sys.argv[1:]
    update_all = "--all" in sys.argv[1:]

    text = VALUES_PATH.read_text(encoding="utf-8")
    lines = text.splitlines()

    print(f"Scanning {VALUES_PATH} for digest-pinned images...")
    stale, unresolved, fetch_errors = find_stale_digests(lines, VALUES_PATH)

    if unresolved:
        print(f"\n{len(unresolved)} pin(s) could not be resolved to a repository (skipped):")
        for p in unresolved:
            print(f"  line {p['line']}: {p['version']}")

    if fetch_errors:
        print(f"\n{len(fetch_errors)} fetch error(s):")
        for repository, version, error, pin_lines in fetch_errors:
            print(f"  {repository}:{version}  {error}  (lines {', '.join(map(str, pin_lines))})")

    to_update = stale if update_all else [s for s in stale if not s[5]]
    skipped_sliding = [] if update_all else [s for s in stale if s[5]]

    if not to_update:
        if skipped_sliding:
            print(f"\nNo stale pinned digests found — nothing to update. "
                  f"({len(skipped_sliding)} sliding digest(s) drifted; pass --all to include them.)")
        else:
            print("\nNo stale digests found — nothing to do.")
        sys.exit(1 if fetch_errors else 0)

    print(f"\n{len(to_update)} stale digest(s){' (dry-run, not writing)' if dry_run else ''}:")
    for repository, version, old_digest, new_digest, pin_lines, sliding in to_update:
        print(f"  {repository}:{version}{'  (sliding)' if sliding else ''}")
        print(f"    old: sha256:{old_digest}")
        print(f"    new: {new_digest}")
        print(f"    lines: {', '.join(map(str, pin_lines))}")
        if not dry_run:
            new_hex = new_digest.split("sha256:", 1)[1]
            text = text.replace(old_digest, new_hex)

    if skipped_sliding:
        print(f"\n{len(skipped_sliding)} sliding digest(s) not updated (pass --all to include):")
        for repository, version, old_digest, new_digest, pin_lines, sliding in skipped_sliding:
            print(f"  {repository}:{version}")
            print(f"    old: sha256:{old_digest}")
            print(f"    new: {new_digest}")
            print(f"    lines: {', '.join(map(str, pin_lines))}")

    if not dry_run:
        VALUES_PATH.write_text(text, encoding="utf-8")
        print(f"\nWrote {len(to_update)} updated digest(s) to {VALUES_PATH}.")
        print("Re-render the chart to confirm (verify-podiumd.py or /helm-render-all) before committing.")

    sys.exit(1 if fetch_errors else 0)


if __name__ == "__main__":
    main()
