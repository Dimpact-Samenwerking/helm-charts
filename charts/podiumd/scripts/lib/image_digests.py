"""Verifies every digest-pinned image in values.yaml still matches its live
upstream registry digest — report-only, never writes to values.yaml (see
set-image-digests.py for that)."""
import re
import urllib.error

from lib.chart import load_yaml, subchart_default_repository
from lib.registry import is_sliding_tag, parse_repo, registry_tag_exists

# One "tag: <version>@sha256:<digest>" pin per match, quoted or bare.
DIGEST_PIN_RE = re.compile(
    r'^(?P<indent>\s*)tag:\s*"?(?P<version>[\w][\w.\-]*)@sha256:(?P<digest>[0-9a-f]{64})"?\s*(?:#.*)?$'
)
# An active (uncommented) sibling "repository:" key.
ACTIVE_REPO_RE = re.compile(
    r'^(?P<indent>\s*)repository:\s*"?(?P<repo>[\w][\w.\-]*(?:/[\w.\-]+)*)"?\s*(?:#.*)?$'
)
# A commented-out "#repository: <value>" key, left as a hint for components
# whose real repository is overridden at the gemeente/deployment level.
COMMENTED_REPO_RE = re.compile(
    r'^\s*#\s*repository:\s*"?(?P<repo>[\w][\w.\-]*(?:/[\w.\-]+)*)"?\s*$'
)
# A one-line "# host/repo:tag[@sha256:...]" reference comment, placed above
# the "image:" block for the same override components. Tolerates a stray
# "@" right after the colon, seen on one existing comment in values.yaml.
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
    values.yaml, with its resolved upstream repository. A single image (e.g.
    nginx-unprivileged) is typically pinned many times across the file."""
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


def check_image_digests(chart_dir):
    """Report-only: verify every digest-pinned image in values.yaml against
    its live upstream registry digest, to catch pins that are stale (tag
    unchanged, but upstream re-published it with new base/security layers).
    One network request per unique (repository, version) pair. Never writes
    to values.yaml — use set-image-digests.py to fix confirmed-stale pins.

    A mismatch is classified sliding — expected drift, reported but not
    counted as a failure — when this repo's own git history shows the tag
    has changed digest before, or (only if that's inconclusive) the
    registry currently has a more specific sibling tag at the same digest;
    see lib.registry.is_sliding_tag. Otherwise it's a component's own
    release tag, which should never legitimately change once published —
    a mismatch there is a real failure worth investigating.

    A pin whose "tag:" has no resolvable "repository:" of its own in
    values.yaml (resolve_pin_repo) falls back to the same component's
    vendored subchart default (lib.chart.subchart_default_repository) —
    the repository Helm itself merges in at render time when podiumd
    doesn't override it. Still unresolved after that (dependency/.tgz
    missing, or the subchart doesn't default one there either) is skipped,
    same as before."""
    values_path = chart_dir / "values.yaml"
    lines = values_path.read_text(encoding="utf-8").splitlines()
    pins = scan_digest_pins(lines)

    chart_yaml_path = chart_dir / "Chart.yaml"
    deps = load_yaml(chart_yaml_path).get("dependencies", []) if chart_yaml_path.is_file() else []
    subchart_cache = {}
    for p in pins:
        if not p["repository"]:
            p["repository"] = subchart_default_repository(chart_dir, lines, p["line"], deps, subchart_cache)

    unresolved = [p for p in pins if not p["repository"]]
    targets = {}
    for p in pins:
        if p["repository"]:
            targets.setdefault((p["repository"], p["version"]), []).append(p)

    print(f"Found {len(pins)} digest-pinned image(s), {len(targets)} unique image:tag to check "
          f"({len(unresolved)} unresolved, skipped)")

    matched = 0
    mismatches = []
    sliding_mismatches = []
    fetch_errors = []

    for (repository, version), group in sorted(targets.items()):
        host, repo_path = parse_repo(repository)
        pinned_digest = group[0]["digest"]
        lines_str = ", ".join(str(p["line"]) for p in group)

        digest, error = None, None
        for _attempt in range(2):
            try:
                exists, digest = registry_tag_exists(host, repo_path, version)
                error = None if exists else "tag not found upstream"
                break
            except (urllib.error.URLError, OSError) as e:
                error = str(e)

        if error:
            fetch_errors.append((repository, version, error, lines_str))
            print(f"  [FETCH-ERR] {host}/{repo_path}:{version}  {error}  (lines {lines_str})")
        elif digest and digest != f"sha256:{pinned_digest}":
            sliding = is_sliding_tag(values_path, host, repo_path, version, digest)
            if sliding:
                sliding_mismatches.append((repository, version, pinned_digest, digest, lines_str))
                print(f"  [SLIDING  ] {host}/{repo_path}:{version}  (known to drift — "
                      f"digest change is expected, not a failure)")
                print(f"      pinned:   sha256:{pinned_digest}")
                print(f"      upstream: {digest}")
                print(f"      lines:    {lines_str}")
            else:
                mismatches.append((repository, version, pinned_digest, digest, lines_str))
                print(f"  [MISMATCH ] {host}/{repo_path}:{version}")
                print(f"      pinned:   sha256:{pinned_digest}")
                print(f"      upstream: {digest}")
                print(f"      lines:    {lines_str}")
        else:
            matched += 1

    print()
    if unresolved:
        print(f"{len(unresolved)} pin(s) could not be resolved to a repository (skipped):")
        for p in unresolved:
            print(f"  line {p['line']}: {p['version']}")
        print()

    if sliding_mismatches:
        print(f"{len(sliding_mismatches)} sliding base-image digest(s) drifted (expected, not a "
              f"failure) — pass --all to set-image-digests.py to refresh them too.")
    if mismatches:
        print(f"Run set-image-digests.py to refresh the {len(mismatches)} stale pinned digest(s) above.")

    detail = (f"{matched}/{len(targets)} matched, {len(sliding_mismatches)} sliding (expected drift), "
              f"{len(mismatches)} stale, {len(fetch_errors)} fetch error(s)")
    if mismatches or fetch_errors:
        return False, detail
    return True, detail
