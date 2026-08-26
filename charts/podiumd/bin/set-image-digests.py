#!/usr/bin/env python3
"""
Refresh stale digest pins in charts/podiumd/values.yaml — a pin whose
version tag is unchanged but upstream re-published it with new
base/security layers, so the multi-arch index digest changed. Fetches the
live "Docker-Content-Digest" for each unique "<repository>:<tag>" pin and,
if it differs, replaces every occurrence of the old digest with the new
one (byte-identical otherwise). See find_stale_digests for how a
repository is resolved for a pin, and lib.registry.is_sliding_tag for why
some mismatches are reported but left untouched by default.

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

from lib.chart import load_yaml, subchart_default_repository, subchart_needs_vendoring
from lib.dependencies import check_dependencies as vendor_dependencies, ensure_repos_configured
from lib.registry import is_sliding_tag, parse_repo, registry_tag_exists

CHART_DIR = SCRIPT_DIR.parents[0]
VALUES_PATH = CHART_DIR / "values.yaml"

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
    never legitimately change once published.

    A pin whose "tag:" has no resolvable "repository:" of its own falls
    back to the same component's vendored subchart default — see
    lib.chart.subchart_default_repository. If that's still unresolved
    specifically because the vendored .tgz isn't there yet (see
    lib.chart.subchart_needs_vendoring), vendors dependencies once (a real
    `helm dependency update`) and retries — never for a pin that has no
    matching Chart.yaml dependency at all, since vendoring can't help
    that one regardless."""
    pins = scan_digest_pins(lines)

    chart_dir = values_path.parent
    chart_yaml_path = chart_dir / "Chart.yaml"
    deps = load_yaml(chart_yaml_path).get("dependencies", []) if chart_yaml_path.is_file() else []
    subchart_cache = {}
    for p in pins:
        if not p["repository"]:
            p["repository"] = subchart_default_repository(chart_dir, lines, p["line"], deps, subchart_cache)

    still_unresolved = [p for p in pins if not p["repository"]]
    if any(subchart_needs_vendoring(chart_dir, lines, p["line"], deps) for p in still_unresolved):
        print("Some pin(s) rely on their subchart's own default repository, but it isn't "
              "vendored yet — running `helm dependency update` once to resolve them too.")
        ok, msg = ensure_repos_configured()
        if not ok:
            print(f"WARNING: {msg} — those pin(s) will stay unresolved", file=sys.stderr)
        else:
            ok, msg = vendor_dependencies(chart_dir)
            if not ok:
                print(f"WARNING: {msg} — those pin(s) will stay unresolved", file=sys.stderr)
        subchart_cache.clear()
        for p in still_unresolved:
            p["repository"] = subchart_default_repository(chart_dir, lines, p["line"], deps, subchart_cache)

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
    if "-h" in sys.argv[1:] or "--help" in sys.argv[1:]:
        print(__doc__)
        sys.exit(0)
    dry_run = "--dry-run" in sys.argv[1:]
    update_all = "--all" in sys.argv[1:]

    text = VALUES_PATH.read_text(encoding="utf-8")
    lines = text.splitlines()

    print(f"Scanning {VALUES_PATH} for digest-pinned images...")
    stale, unresolved, fetch_errors = find_stale_digests(lines, VALUES_PATH)

    if unresolved:
        print(f"\n{len(unresolved)} pin(s) could not be resolved to a repository (skipped):")
        for p in unresolved:
            print(f"  values.yaml:{p['line']}: {p['version']}")

    if fetch_errors:
        print(f"\n{len(fetch_errors)} fetch error(s):")
        for repository, version, error, pin_lines in fetch_errors:
            print(f"  {repository}:{version}  {error}  (values.yaml:{', '.join(map(str, pin_lines))})")

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
        print(f"    lines: values.yaml:{', '.join(map(str, pin_lines))}")
        if not dry_run:
            new_hex = new_digest.split("sha256:", 1)[1]
            text = text.replace(old_digest, new_hex)

    if skipped_sliding:
        print(f"\n{len(skipped_sliding)} sliding digest(s) not updated (pass --all to include):")
        for repository, version, old_digest, new_digest, pin_lines, sliding in skipped_sliding:
            print(f"  {repository}:{version}")
            print(f"    old: sha256:{old_digest}")
            print(f"    new: {new_digest}")
            print(f"    lines: values.yaml:{', '.join(map(str, pin_lines))}")

    if not dry_run:
        VALUES_PATH.write_text(text, encoding="utf-8")
        print(f"\nWrote {len(to_update)} updated digest(s) to {VALUES_PATH}.")
        print("Re-render the chart to confirm (verify-podiumd.py or /helm-render-all) before committing.")

    sys.exit(1 if fetch_errors else 0)


if __name__ == "__main__":
    main()
