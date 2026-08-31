"""Verifies every digest-pinned image in values.yaml still matches its live
upstream registry digest — report-only, never writes to values.yaml (see
fix-image-digests for that)."""
import re
import urllib.error

from lib.chart import load_yaml, subchart_default_repository
from lib.registry import UNVERIFIABLE_HOSTS, is_sliding_tag, parse_repo, registry_tag_exists

# One "tag: <version>@sha256:<digest>" pin per match, quoted or bare.
DIGEST_PIN_RE = re.compile(
    r'^(?P<indent>\s*)tag:\s*"?(?P<version>[\w][\w.\-]*)@sha256:(?P<digest>[0-9a-f]{64})"?\s*(?:#.*)?$'
)
# An active (uncommented) sibling "repository:" key.
ACTIVE_REPO_RE = re.compile(
    r'^(?P<indent>\s*)repository:\s*"?(?P<repo>[\w][\w.\-]*(?:/[\w.\-]+)*)"?\s*(?:#.*)?$'
)
# An active (uncommented) sibling "registry:" key — some pins (e.g.
# redis-ha's opstree/redis images) split the host out of "repository:"
# into its own key, unlike the combined "repository: <host>/<path>" style
# used everywhere else in this file. podiumd.image (_helpers.tpl) renders
# both styles identically ("{{ if .registry }}{{ .registry }}/{{ end
# }}{{ .repository }}"), so this is purely stylistic — but resolve_pin_repo
# must still honor it, or a split-style pin gets looked up against the
# wrong (guessed) registry. See find_sibling_registry.
ACTIVE_REGISTRY_RE = re.compile(
    r'^(?P<indent>\s*)registry:\s*"?(?P<registry>[\w][\w.\-]*)"?\s*(?:#.*)?$'
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


def find_sibling_registry(lines, tag_line_index, tag_indent):
    """The value of a sibling "registry:" key at the same indent as the
    "tag:" pin at tag_line_index, if present — e.g. redis-ha's split
    `registry: quay.io` / `repository: opstree/redis` style, as opposed to
    the single combined "repository: quay.io/opstree/redis" style used
    everywhere else in this file. Returns None if there's no such key
    (the common case)."""
    for i in range(tag_line_index - 1, max(tag_line_index - 15, -1), -1):
        raw = lines[i]
        if not raw.strip():
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        if indent < tag_indent:
            break
        m = ACTIVE_REGISTRY_RE.match(raw)
        if m and indent == tag_indent:
            return m.group("registry")
    return None


def find_inconsistent_version_pins(pins):
    """Every repository pinned as a literal (non-alias) "tag:" in more than
    one place across values.yaml — always a real problem, just one of two
    different kinds:

    "duplicate" — every occurrence currently agrees on the exact same
    (version, digest). There's no legitimate reason two spots need to be
    hand-typed identically instead of one being a YAML alias ("*name") to
    the other's anchor ("&name") — confirmed by hand: curlimages/curl is
    defined once via "&curlImage" and reused via "*curlImage" in three
    places, but ALSO hand-duplicated verbatim at kiss.settings.elastic.
    indexTemplateImage, which isn't protected by that alias at all and
    can silently drift the next time the anchor is bumped without anyone
    remembering this spot exists.

    "drift" — the occurrences disagree: different versions, or the same
    version pinned with a different digest (e.g. a sliding tag refreshed
    at one spot but not the other, invisible to a version-only
    comparison). This COULD be a deliberate variant of the same
    repository (e.g. python:3.14-slim vs python:3.14-alpine share the
    exact repository "library/python", differing only in tag suffix) —
    but as of 2026-08-26 no repository in this chart is actually pinned
    at more than one version anywhere, so there's no real precedent this
    would break; a real future variant pin would need to fail loudly here
    too rather than let genuine drift slide through unnoticed.

    Grouped by the exact "repository:" string, not by basename (see
    lib.image_version.image_basename) — a shared basename across
    different orgs/paths (docker.io/x/tool vs ghcr.io/y/tool) isn't the
    same image at all, so basename grouping would false-positive there.

    Returns {repository: {"kind": "duplicate"|"drift",
    "pins": [((version, digest), [line, ...]), ...]}} for every
    repository pinned literally in more than one place; a repository
    pinned only once (the common case) is omitted entirely."""
    by_repo = {}
    for p in pins:
        if not p["repository"]:
            continue
        by_repo.setdefault(p["repository"], []).append((p["version"], p["digest"], p["line"]))

    findings = {}
    for repo, entries in by_repo.items():
        if len(entries) < 2:
            continue
        pairs = {}
        for version, digest, line in entries:
            pairs.setdefault((version, digest), []).append(line)
        findings[repo] = {"kind": "duplicate" if len(pairs) == 1 else "drift", "pins": list(pairs.items())}
    return findings


def resolve_pin_repo(lines, tag_line_index, tag_indent):
    """Resolve the upstream repository for a "tag:" pin at tag_line_index.
    Most pins have an active sibling "repository:" key. A minority of
    components (e.g. office_converter, opa, solr-operator) deliberately
    comment their "repository:" out so gemeente-level ACR-mirror overrides
    take precedence — for those, fall back to the "# host/repo:tag" style
    reference comment placed above the "image:" block, or a commented-out
    "#repository: <value>" key at the same indent. A sibling "registry:"
    key (see find_sibling_registry) is prefixed on when present, so a
    split-style pin resolves to the same host/path a combined-style pin
    would."""
    for i in range(tag_line_index - 1, max(tag_line_index - 15, -1), -1):
        raw = lines[i]
        if not raw.strip():
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        if indent < tag_indent:
            break
        m = ACTIVE_REPO_RE.match(raw)
        if m and indent == tag_indent:
            repo = m.group("repo")
            registry = find_sibling_registry(lines, tag_line_index, tag_indent)
            return f"{registry}/{repo}" if registry else repo
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
    to values.yaml — use fix-image-digests to fix confirmed-stale pins.

    A mismatch is classified sliding — expected drift, e.g. a floating
    base-image tag republished with new security patches — when this
    repo's own git history shows the tag has changed digest before, or
    (only if that's inconclusive) the registry currently has a more
    specific sibling tag at the same digest; see lib.registry.
    is_sliding_tag. Otherwise it's a component's own release tag, which
    should never legitimately change once published. Either way the pin
    is stale and FAILS the check — "expected" only means the drift itself
    isn't surprising, not that the stale pin should be left alone; run
    fix-image-digests to refresh it (sliding or not, it always
    rewrites every stale pin it finds).

    A pin whose "tag:" has no resolvable "repository:" of its own in
    values.yaml (resolve_pin_repo) falls back to the same component's
    vendored subchart default (lib.chart.subchart_default_repository) —
    the repository Helm itself merges in at render time when podiumd
    doesn't override it. Still unresolved after that (dependency/.tgz
    missing, or the subchart doesn't default one there either) is skipped,
    same as before.

    A fetch error against a host in lib.registry.UNVERIFIABLE_HOSTS (one
    that rejects even an anonymous manifest read outright — confirmed not
    fixable by a better anonymous-token flow) is reported separately as
    unverifiable rather than a genuine FETCH-ERR, and never fails the
    check on its own — it can't succeed from an unprivileged environment
    regardless of whether the pin itself is correct.

    Any repository pinned literally in more than one place in values.yaml
    (see find_inconsistent_version_pins) FAILS the check, one of two ways:
    a [DUPLICATE-PIN] (every occurrence agrees — should be a YAML alias to
    a shared anchor instead of hand-duplicated text, since nothing then
    stops the un-aliased copy from silently drifting on a future bump) or
    a [VERSION-DRIFT] (the occurrences disagree — different versions, or
    the same version pinned with a different digest, e.g. a sliding tag
    refreshed at one spot but not the other)."""
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
    unverifiable = []

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

        if error and host in UNVERIFIABLE_HOSTS:
            unverifiable.append((repository, version, error, lines_str))
            print(f"  [UNVERIFIABLE] {host}/{repo_path}:{version}  {error}  (values.yaml:{lines_str})")
        elif error:
            fetch_errors.append((repository, version, error, lines_str))
            print(f"  [FETCH-ERR] {host}/{repo_path}:{version}  {error}  (values.yaml:{lines_str})")
        elif digest and digest != f"sha256:{pinned_digest}":
            sliding = is_sliding_tag(values_path, host, repo_path, version, digest)
            if sliding:
                sliding_mismatches.append((repository, version, pinned_digest, digest, lines_str))
                print(f"  [SLIDING  ] {host}/{repo_path}:{version}  (known to drift — "
                      f"refresh with fix-image-digests)")
                print(f"      pinned:   sha256:{pinned_digest}")
                print(f"      upstream: {digest}")
                print(f"      lines:    values.yaml:{lines_str}")
            else:
                mismatches.append((repository, version, pinned_digest, digest, lines_str))
                print(f"  [MISMATCH ] {host}/{repo_path}:{version}")
                print(f"      pinned:   sha256:{pinned_digest}")
                print(f"      upstream: {digest}")
                print(f"      lines:    values.yaml:{lines_str}")
        else:
            matched += 1

    print()
    if unresolved:
        print(f"{len(unresolved)} pin(s) could not be resolved to a repository (skipped):")
        for p in unresolved:
            print(f"  values.yaml:{p['line']}: {p['version']}")
        print()

    if unverifiable:
        print(f"{len(unverifiable)} image(s) on a registry this environment can't reach anonymously "
              f"(not counted as a failure — see lib.registry.UNVERIFIABLE_HOSTS):")
        for repository, version, error, lines_str in unverifiable:
            print(f"  {repository}:{version}  {error}  (values.yaml:{lines_str})")
        print()

    if sliding_mismatches:
        print(f"Run fix-image-digests to refresh the {len(sliding_mismatches)} "
              f"sliding digest(s) above.")
    if mismatches:
        print(f"Run fix-image-digests to refresh the {len(mismatches)} stale pinned digest(s) above.")

    inconsistent = find_inconsistent_version_pins(pins)
    duplicates = {r: f for r, f in inconsistent.items() if f["kind"] == "duplicate"}
    drifted = {r: f for r, f in inconsistent.items() if f["kind"] == "drift"}

    for repository, finding in duplicates.items():
        (version, digest), pin_lines = finding["pins"][0]
        lines_str = ", ".join(str(n) for n in sorted(pin_lines))
        print(f"  [DUPLICATE-PIN] {repository}:{version}  hand-duplicated identically at "
              f"{len(pin_lines)} places (values.yaml:{lines_str}) instead of a shared YAML anchor "
              f'("&name" once, "*name" everywhere else) — the un-aliased cop{"y" if len(pin_lines) == 2 else "ies"} '
              f"can silently drift the next time this image is bumped elsewhere")

    for repository, finding in drifted.items():
        print(f"  [VERSION-DRIFT] {repository} pinned at {len(finding['pins'])} different versions/digests "
              f"across values.yaml:")
        for (version, digest), pin_lines in finding["pins"]:
            lines_str = ", ".join(str(n) for n in pin_lines)
            print(f"      {version}@sha256:{digest}  (values.yaml:{lines_str})")

    detail = (f"{matched}/{len(targets)} matched, {len(sliding_mismatches)} sliding (stale), "
              f"{len(mismatches)} stale, {len(fetch_errors)} fetch error(s), "
              f"{len(unverifiable)} unverifiable, "
              f"{len(duplicates)} duplicate pin(s), {len(drifted)} version-drift finding(s)")
    if mismatches or sliding_mismatches or fetch_errors or inconsistent:
        return False, detail
    return True, detail
