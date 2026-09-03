"""Chart.yaml/values.yaml helpers shared by every script that resolves a
podiumd dependency, pulls a specific chart version, or walks a values tree
for image references."""
import re
import shutil
import sys
import tarfile
import tempfile
from pathlib import Path

import yaml

from lib.gitutil import git_show_yaml
from lib.procutil import run
from lib.registry import parse_repo, registry_tag_exists

# A BOM breaks YAML tooling that doesn't expect one. Shared by
# verify-podiumd (detects and reports it — a verify script never writes
# to a tracked file) and fix-utf8-bom (the fixer).
UTF8_BOM = b"\xef\xbb\xbf"

# component (name or alias) -> dotted values.yaml path(s) for its own image
# block(s), for components that ship more than one independently-versioned
# image (e.g. ZAC alone bundles 10+ — opa, solr, zookeeper, curl,
# gotenberg...) with nothing in the chart itself saying which one is "the
# app" the version-management scripts (verify/update/show-component-
# baseline-version.py) should act on. This is that one small, unavoidable
# hint — just a values.yaml path, not a registry or repo, and only needed
# for multi-image components; anything not listed here defaults to
# DEFAULT_IMAGE_PATHS. Shared here (rather than copy-pasted per script, as
# it used to be) so a new multi-image component only needs adding once.
COMPONENT_IMAGE_PATHS = {
    "zgw-office-addin": ["frontend.image", "backend.image"],
    # The default Keycloak SERVER image the operator stamps onto Keycloak
    # CRs that don't specify their own — deliberately overridden in
    # values.yaml to run a Keycloak version ahead of whatever this operator
    # chart version's own appVersion defaults to. NOT operator.image itself:
    # that one is intentionally left with no override at all, since the
    # adfinis chart's own template already falls back to
    # "{{ .Values.operator.image.tag | default .Chart.AppVersion }}" with a
    # matching "sha:" bundled for that same appVersion — an explicit
    # override there would only add a way for tag and digest to drift apart
    # again. Bump the keycloak-operator dependency's own chart version in
    # Chart.yaml to move the operator itself. Uses the adfinis chart's own
    # split "tag:" + sibling "sha:" convention instead of an embedded
    # @sha256 digest — see update-component-version's SPLIT_TAG_SHA_PATHS
    # for the write side.
    "keycloak-operator": ["operator.config.keycloakImage"],
    # The real running OpenBao SERVER (the upstream openbao-helm
    # subchart's own "server" key) — NOT "openbao.configuration.job.image",
    # which despite reusing the same OpenBao binary is podiumd's own
    # one-off post-deploy bao-config Job (enables OIDC auth, kv-v2 mount,
    # uploader policy — see the values.yaml comment above that key), not
    # the primary application. "server.image" has an explicit
    # "repository:" override in values.yaml but a blank "tag:" (relies on
    # the chart's own appVersion default) — image_paths_for callers still
    # resolve a real repository from that override alone.
    "openbao": ["server.image"],
    # ITA has no single "app" image at all — web and poller are two
    # co-equal images, same lockstep shape as zgw-office-addin's own
    # frontend+backend split (both happen to share one version here, but
    # that's not guaranteed by the chart itself, hence listing both
    # rather than picking one as "the" primary).
    "internetaakafhandeling": ["web.image", "poller.image"],
}
DEFAULT_IMAGE_PATHS = ["image"]


def image_paths_for(component):
    return COMPONENT_IMAGE_PATHS.get(component, DEFAULT_IMAGE_PATHS)


# component (name, not alias — same convention as COMPONENT_IMAGE_PATHS) ->
# dotted values.yaml path(s), each pointing DIRECTLY at a bare version
# string — not the "<path>.image.tag" shape COMPONENT_IMAGE_PATHS/
# DEFAULT_IMAGE_PATHS assume (see lib.upgradedoc.actual_app_version, which
# tries these as a second pass, unsuffixed, only once every image_paths_for
# candidate has failed to resolve a tag). Exists for a component whose real
# app version genuinely isn't expressed as an "image: {repository, tag}"
# block at all:
# - eck-stack (kiss-eck): the ECK operator's own CRD convention — a bare
#   "version:" field per managed resource (eck-elasticsearch/eck-kibana/
#   eck-enterprise-search all track the SAME Elastic stack version in
#   lockstep here), which the operator maps to real container images
#   internally. First of the two that resolves wins, same "no single
#   canonical one, list several" reasoning as COMPONENT_IMAGE_PATHS' own
#   multi-image entries — eck-enterprise-search deliberately excluded since
#   it's disabled by default in this chart (see its own values.yaml
#   comment), so it's not the best of the three to lead with either way.
# - redis-operator: the OPERATOR's own image (as opposed to redis-ha, the
#   database instance it manages, which DOES use the ordinary "image:"
#   shape) — the upstream chart's own "imageName:"/"imageTag:" convention,
#   two separate sibling string fields instead of one nested "image:" dict.
COMPONENT_VERSION_PATHS = {
    "eck-stack": ["eck-elasticsearch.version", "eck-kibana.version"],
    "redis-operator": ["redisOperator.imageTag"],
}


def version_paths_for(component):
    return COMPONENT_VERSION_PATHS.get(component, [])


# component (name, not alias) -> the sibling dotted path holding a
# COMPONENT_VERSION_PATHS entry's own repository — for the rare case
# where that repository IS explicitly overridable in podiumd's OWN
# values.yaml (redis-operator's own "imageName:"/"imageTag:" sibling-
# field convention), so paths_by_repository/find_images_without_
# repository can resolve one at all; a bare "version:" field with no
# such sibling (eck-stack's own two entries) is correctly left out —
# there is no repository override to find here, by design (the ECK
# operator maps that version to its own internal images).
COMPONENT_VERSION_REPOSITORY_PATHS = {
    "redis-operator": "redisOperator.imageName",
}


def version_repository_path_for(component):
    return COMPONENT_VERSION_REPOSITORY_PATHS.get(component)


def load_yaml(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


# A bare MAJOR.MINOR.PATCH version, exactly — e.g. podiumd's own Chart.yaml
# "version:", or a --baseline/target argument. Anything else (a suffix, a
# git ref, a flag) is rejected up front by every caller, rather than
# silently being treated as a literal version.
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


def chart_version(chart_yaml_path):
    return str(load_yaml(chart_yaml_path)["version"])


RELEASE_BASELINES_FILE_NAME = "release-baseline.yaml"


def _release_baselines(chart_dir):
    """The parsed contents of chart_dir/release-baseline.yaml — upgrade_
    docs (the incremental baseline _UPGRADE_PATHS/*.md and docs/images/
    images-<target>.yaml are written against) and release_table (the
    cumulative baseline release-table.csv was last generated against;
    see upgrade_docs_baseline/release_table_baseline below for why
    podiumd needs two baselines instead of one) — or {} if the file
    doesn't exist yet. Not a public accessor itself: callers want
    upgrade_docs_baseline/release_table_baseline below, which each read
    one specific key."""
    path = chart_dir / RELEASE_BASELINES_FILE_NAME
    if not path.is_file():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def upgrade_docs_baseline(chart_dir):
    """The incremental baseline _UPGRADE_PATHS/*.md and docs/images/
    images-<target>.yaml are written against — the immediately
    preceding release, advanced on every release cycle (see
    create-podiumd-version). None if release-baseline.yaml or this key
    doesn't exist yet."""
    return _release_baselines(chart_dir).get("upgrade_docs")


def release_table_baseline(chart_dir):
    """The cumulative baseline release-table.csv (the Confluence
    release-notes export) was last generated against — advanced only on
    a minor version bump (see create-podiumd-version), left untouched by
    a patch bump. None if release-baseline.yaml or this key doesn't
    exist yet."""
    return _release_baselines(chart_dir).get("release_table")


def write_release_baselines(chart_dir, upgrade_docs=None, release_table=None):
    """Read-modify-write chart_dir/release-baseline.yaml, updating only
    whichever of upgrade_docs/release_table is given (None leaves that
    key untouched, whatever it already was) — the single write path
    shared by create-podiumd-version (writes upgrade_docs on every
    release cycle, release_table only on a minor bump) and
    change-podiumd-baseline (writes upgrade_docs only, never
    release_table), so neither script risks clobbering the other's own
    key by writing a fresh two-key file from scratch."""
    path = chart_dir / RELEASE_BASELINES_FILE_NAME
    data = _release_baselines(chart_dir)
    if upgrade_docs is not None:
        data["upgrade_docs"] = upgrade_docs
    if release_table is not None:
        data["release_table"] = release_table
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def get_path(node, dotted_path):
    for key in dotted_path.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def replace_scalar_value(line, new_value):
    """Replace a "key: <value>" line's scalar value, preserving indent, key,
    quote style, and any trailing comment. Used to bump a version/tag pin in
    place without a full yaml.safe_load+dump round trip, which would lose
    comments and reformat the rest of the file."""
    m = re.match(r'^(?P<indent>\s*)(?P<key>[^:\n]+:)\s*(?P<quote>["\']?)'
                 r'(?P<value>.*?)(?P=quote)\s*(?P<comment>#.*)?\s*$', line)
    if not m:
        raise SystemExit(f"error: could not parse line for replacement: {line!r}")
    quote = m.group("quote")
    comment = f"  {m.group('comment')}" if m.group("comment") else ""
    return f"{m.group('indent')}{m.group('key')} {quote}{new_value}{quote}{comment}\n"


def find_dependency(deps, name_or_alias):
    """The Chart.yaml dependency entry matching this name or alias, or None
    if there isn't one — pure lookup, no I/O; callers load `deps` themselves
    (usually `chart_yaml["dependencies"]`) and decide how to report a miss."""
    for dep in deps:
        if dep["name"] == name_or_alias or dep.get("alias") == name_or_alias:
            return dep
    return None


def find_app_versions(values, values_key, image_paths):
    """[(image_path, tag), ...] for every image_paths entry (see
    image_paths_for) that has an explicit tag override under
    values[values_key] — empty if the component relies entirely on its
    chart's own image defaults. Shared by show-component-baseline-version
    and show-image-baseline-version (which this lets delegate its own
    image-only lookup to, via component_state_at_ref below)."""
    base = values.get(values_key, {}) if isinstance(values, dict) else {}
    versions = []
    for path in image_paths:
        tag = get_path(base, f"{path}.tag")
        if tag:
            versions.append((path, tag))
    return versions


def component_state_at_ref(repo_root, ref, chart_dir_relpath, component):
    """(dep, values_key, image_paths, app_versions, error) for
    `component`'s Chart.yaml dependency entry + declared image tag(s) as
    they were at ref, via `git show` (no checkout needed) — every path
    show-component-baseline-version and show-image-baseline-version each
    need to look up a component's baseline state, since neither ever
    needs Chart.yaml/values.yaml without the other. On failure, error is
    a ready-to-print reason (no "error: " prefix — callers format that
    themselves) and the other four are None; on success error is None.
    Never raises: a caller-facing lookup like this treats "not found" as
    an ordinary, reportable outcome, not an exceptional one."""
    chart_yaml = git_show_yaml(repo_root, ref, f"{chart_dir_relpath}/Chart.yaml")
    if chart_yaml is None:
        return None, None, None, None, f"could not read {chart_dir_relpath}/Chart.yaml at {ref}"
    dep = find_dependency(chart_yaml.get("dependencies", []), component)
    if not dep:
        return None, None, None, None, (f"no dependency named or aliased '{component}' "
                                         f"in {chart_dir_relpath}/Chart.yaml at {ref}")
    values = git_show_yaml(repo_root, ref, f"{chart_dir_relpath}/values.yaml") or {}
    values_key = dep.get("alias", dep["name"])
    image_paths = image_paths_for(component)
    app_versions = find_app_versions(values, values_key, image_paths)
    return dep, values_key, image_paths, app_versions, None


def chart_ref(dep):
    """Return (ref, extra_repo_url_or_None) for `helm pull`, or (None, None)
    for a local path repository ("file://...") that must already be
    vendored — it has no remote to pull from."""
    repo = dep["repository"]
    if repo.startswith("oci://"):
        return f"{repo}/{dep['name']}", None
    if repo.startswith("@"):
        return f"{repo[1:]}/{dep['name']}", None
    if repo.startswith("http://") or repo.startswith("https://"):
        return dep["name"], repo
    if repo.startswith("file://"):
        return None, None
    raise SystemExit(f"error: unsupported repository scheme: {repo}")


def local_chart_dir(chart_dir, dep):
    """The directory a "file://..." dependency's own repository actually
    points at, resolved relative to chart_dir (Helm's own convention for
    local path dependencies) — None for any other repository scheme.
    `helm pull` can never fetch this (see chart_ref) — a caller wanting
    that dependency's own Chart.yaml/values.yaml reads them straight from
    here instead, no pull involved."""
    repo = dep["repository"]
    if not repo.startswith("file://"):
        return None
    return (chart_dir / repo[len("file://"):]).resolve()


def pull_chart(dep, version, dest):
    """Pull a chart version via helm. Returns (ok, stderr)."""
    ref, repo_url = chart_ref(dep)
    if ref is None:
        return False, (f"dependency '{dep['name']}' uses a local path repository "
                        f"({dep['repository']}) — not fetchable remotely")
    cmd = ["helm", "pull", ref, "--version", version, "--untar", "--untardir", str(dest)]
    if repo_url:
        cmd += ["--repo", repo_url]
    result = run(cmd, capture_output=True, text=True)
    return result.returncode == 0, result.stderr.strip()


def pulled_chart_dir(tmpdir):
    """The single chart directory `helm pull --untar` produced under tmpdir."""
    chart_dirs = [p for p in Path(tmpdir).iterdir() if p.is_dir()]
    if not chart_dirs:
        raise SystemExit(f"error: helm pull produced no chart directory in {tmpdir}")
    return chart_dirs[0]


def pull_chart_values(dep, version):
    """Pull a chart version into a throwaway temp dir and return its own
    values.yaml (parsed), cleaning up afterward. Raises SystemExit if the
    pull fails."""
    tmpdir = Path(tempfile.mkdtemp(prefix="pull-chart-values-"))
    try:
        ok, stderr = pull_chart(dep, version, tmpdir)
        if not ok:
            raise SystemExit(f"error: could not pull {dep['name']} {version}: {stderr}")
        chart_dir = pulled_chart_dir(tmpdir)
        return yaml.safe_load((chart_dir / "values.yaml").read_text()) or {}
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def verify_chart_version(chart_dir, dep, version):
    """The chart-existence check verify-component-version owns: resolve
    `version` of `dep` via resolve_chart_values (preferring an already-
    vendored charts/<name>-<version>.tgz over a fresh `helm pull` — see
    resolve_chart_values), print a "Checking chart version ... [FOUND/
    MISSING]" line, and exit 1 with a FAIL message if that resolution
    failed. Returns the resolved chart's own values.yaml (parsed) on
    success — verify-component-version's own app-image check needs that
    values.yaml to resolve the image repository/host, so the
    chart-version check itself lives in exactly this one place rather
    than being reimplemented."""
    chart_name = dep["name"]
    print(f"Checking chart version {version!r} for {chart_name}:")
    values, source, error = resolve_chart_values(chart_dir, dep, version)
    status = "FOUND  " if values is not None else "MISSING"
    suffix = f"  ({source})" if values is not None else f"  ({error})"
    print(f"  [{status}] {chart_name} {version}{suffix}")
    if values is None:
        print()
        print("FAIL: chart version does not exist")
        sys.exit(1)
    return values


def check_image_versions(values, image_paths, app_version):
    """[{"path", "repository", "host", "repo_path", "exists", "digest"},
    ...] for every path in `image_paths` (see image_paths_for) that has a
    "repository:" in `values` (a pulled chart's own values.yaml — see
    verify_chart_version/pull_chart_values), checked against app_version on its actual
    upstream registry. Shared by verify-component-version (a human
    pre-checking a version before writing it anywhere) and update-
    component-version.py's own pre-write gate (the same check, reused
    against the SAME pulled values rather than pulling — and checking —
    a second time), so there is exactly one place this logic lives.

    Raises SystemExit if NOT ONE of image_paths has a resolvable
    repository at all — e.g. COMPONENT_IMAGE_PATHS points somewhere this
    chart version doesn't actually have an image (wrong path, or the
    chart restructured) — since a caller can't act on zero results
    either way, and silently reporting "0 checked, all fine" would be
    misleading."""
    repos = [(path, repo) for path in image_paths
             for repo in [get_path(values, f"{path}.repository")] if isinstance(repo, str) and repo]
    if not repos:
        raise SystemExit(f"error: no repository found at {', '.join(f'{p}.repository' for p in image_paths)} "
                          f"— wrong path? see lib.chart.COMPONENT_IMAGE_PATHS")

    results = []
    for path, repo in repos:
        host, repo_path = parse_repo(repo)
        exists, digest = registry_tag_exists(host, repo_path, app_version)
        results.append({"path": path, "repository": repo, "host": host, "repo_path": repo_path,
                         "exists": exists, "digest": digest})
    return results


def version_of(tag):
    return tag.split("@", 1)[0]


KEY_LINE_RE = re.compile(r"^(?P<indent>\s*)(?P<key>[\w.\-]+):(?:\s|$)")


def dotted_key_path(lines, line_index):
    """The dotted path of keys enclosing lines[line_index] (inclusive),
    reconstructed purely from indentation — e.g. "openzaak.image.tag" for
    a "tag:" line nested under "openzaak: > image:". A plain-text
    stand-in for a full YAML-document walk, used by digest-pin scanning
    (lib.image_digests/fix-image-digests), which already has the exact
    source line (and its digest/comment) from a regex match on raw
    `lines` — a full re-parse would lose that line-number association."""
    stack = []
    for raw in lines[:line_index + 1]:
        m = KEY_LINE_RE.match(raw)
        if not m:
            continue
        indent = len(m.group("indent"))
        while stack and stack[-1][0] >= indent:
            stack.pop()
        stack.append((indent, m.group("key")))
    return ".".join(key for _, key in stack)


def subchart_values(chart_dir, dep, version=None):
    """A vendored dependency's own values.yaml (parsed), read straight out
    of its .tgz under chart_dir/charts/ at `version` (default: dep
    ["version"], i.e. the currently-pinned version) — the same file Helm
    merges podiumd's own values.yaml under at render time. None if that
    exact version isn't vendored (not pulled yet, or a different version
    is) or the .tgz doesn't have the expected layout."""
    version = version or dep["version"]
    tgz_path = chart_dir / "charts" / f"{dep['name']}-{version}.tgz"
    if not tgz_path.is_file():
        return None
    try:
        with tarfile.open(tgz_path) as tar:
            member = tar.extractfile(f"{dep['name']}/values.yaml")
            if member is None:
                return None
            return yaml.safe_load(member.read()) or {}
    except (KeyError, tarfile.TarError):
        return None


def subchart_app_version(chart_dir, dep, version=None):
    """A vendored dependency's own Chart.yaml "appVersion" field — the
    real app version a subchart's own template falls back to via Helm's
    own "{{ .Values.<x>.tag | default .Chart.AppVersion }}" convention,
    for a component whose COMPONENT_IMAGE_PATHS-registered image path
    has an explicit but deliberately BLANK "tag:" override in podiumd's
    own values.yaml — e.g. openbao's own "server.image.tag" (see that
    registry entry's own comment): the repository is overridden to pin
    the mirror, but the tag is left for the chart's own pinned appVersion
    to supply, so lib.upgradedoc.actual_app_version's own values.yaml
    lookup alone can never see the real version there at all. Same
    vendored-.tgz-only lookup as subchart_values (no network fallback —
    see resolve_chart_values for that). None if that exact version isn't
    vendored, its Chart.yaml can't be read, or it has no appVersion."""
    version = version or dep["version"]
    tgz_path = chart_dir / "charts" / f"{dep['name']}-{version}.tgz"
    if not tgz_path.is_file():
        return None
    try:
        with tarfile.open(tgz_path) as tar:
            member = tar.extractfile(f"{dep['name']}/Chart.yaml")
            if member is None:
                return None
            chart_yaml = yaml.safe_load(member.read()) or {}
            return chart_yaml.get("appVersion")
    except (KeyError, tarfile.TarError):
        return None


def resolve_chart_values(chart_dir, dep, version, allow_pull=True):
    """(values, source, error) for `dep` at `version` — preferring an
    already-vendored charts/<name>-<version>.tgz (source "vendored", via
    subchart_values, no network) and only falling back to a fresh `helm
    pull` (source "pulled") when allow_pull is True and no vendored copy
    exists at that exact version. This is the "if the proper version is
    already downloaded, use it, don't re-download" shared by
    verify_chart_version and update-component-version's own chart-version
    check — an app-only bump (the common case) targets the SAME chart
    version already vendored on disk, so the pull those previously always
    did was pure waste. On failure — nothing vendored and either pulling
    is disabled or the pull itself failed — values and source are None
    and error is a ready-to-print reason (no "error: " prefix — callers
    format that themselves)."""
    values = subchart_values(chart_dir, dep, version)
    if values is not None:
        return values, "vendored", None
    if not allow_pull:
        return None, None, f"{dep['name']} {version} is not vendored, and pulling is disabled"
    tmpdir = Path(tempfile.mkdtemp(prefix="resolve-chart-values-"))
    try:
        ok, stderr = pull_chart(dep, version, tmpdir)
        if not ok:
            return None, None, stderr
        pulled_dir = pulled_chart_dir(tmpdir)
        return yaml.safe_load((pulled_dir / "values.yaml").read_text(encoding="utf-8")) or {}, "pulled", None
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def primary_image_repositories(chart_dir, dep, own_values, version=None, allow_pull=True):
    """({path: repository_or_None, ...}, error_or_None) for every one of
    dep's own primary image path(s) (see image_paths_for(dep["name"])) —
    THE single place "what repository does this component's primary
    image actually resolve to" is computed, reused by verify-release-
    table-with-podiumd (allow_pull=False — offline only), verify_chart_
    version, and update-component-version, which previously each
    resolved this differently (or, for verify-release-table-with-
    podiumd, not at all for a component relying entirely on its
    subchart's own default repository, e.g. openzaak/openformulieren —
    that was this function's whole reason for existing).

    For each path: podiumd's OWN explicit "repository:" override in
    `own_values` wins if present; otherwise falls back to the subchart's
    own default repository at `version` (default: dep["version"], i.e.
    the CURRENTLY pinned chart version) via resolve_chart_values —
    resolved at most once and reused across every path that needs it,
    not once per path. A path's value is None if NEITHER source has a
    repository there at all; error (from resolve_chart_version, if it
    was ever needed) is None whenever every path resolved via its own
    explicit override, even if the subchart isn't vendored and pulling
    is disabled — nothing depended on the subchart in that case.
    `chart_dir` may itself be None (a caller with no vendored-charts
    location at all, e.g. a pure in-memory test) — treated exactly like
    "not vendored, and pulling is disabled", never raising."""
    values_key = dep.get("alias") or dep["name"]
    version = version or dep["version"]
    results = {}
    subchart_state = None  # lazily filled on first path that needs it: (values_or_None, error_or_None)
    for path in image_paths_for(dep["name"]):
        repo = get_path(own_values, f"{values_key}.{path}.repository")
        if isinstance(repo, str) and repo:
            results[path] = repo
            continue
        if subchart_state is None:
            if chart_dir is None:
                subchart_state = (None, f"no chart_dir given — can't resolve {dep['name']}'s subchart default")
            else:
                values, _source, err = resolve_chart_values(chart_dir, dep, version, allow_pull=allow_pull)
                subchart_state = (values, err)
        values, err = subchart_state
        results[path] = get_path(values, f"{path}.repository") if values is not None else None
    error = subchart_state[1] if subchart_state is not None else None
    return results, error


def strip_registry_host(url):
    """Drop the leading registry host from an image url, keep the rest —
    the same rule as scripts/mirror-strip-registry.py's own
    strip_registry (this chart's images-manifest naming convention, see
    docs/images/acr-mirror-naming.md): a first path segment counts as a
    registry host when it contains "." or ":" (docker.io, quay.io,
    ghcr.io, gcr.io, host:port, ...) or is "localhost"; anything else
    (already-bare "library/redis") is returned unchanged. Duplicated
    here rather than imported — that script lives outside this
    package's own lib/ layout, and the rule is small and stable enough
    not to be worth reaching across for."""
    url = url.strip().split("@", 1)[0]
    head, _, rest = url.partition("/")
    if rest and ("." in head or ":" in head or head == "localhost"):
        return rest
    return url


def paths_by_repository(chart_dir, deps, values, paths, allow_pull=False):
    """{strip_registry_host(repository): [path, ...]} for every path in
    `paths` (e.g. lib.upgradedoc.find_image_tag_paths(values)'s own
    keys) that resolves to a repository — not just each dependency's
    own "primary" image (image_paths_for / primary_image_repositories)
    but every nested sidecar under it too. ZAC's own opa/office_
    converter sidecars are the motivating case: their real repository
    lives in ZAC's OWN vendored subchart values.yaml (a plain top-level
    "opa.image.repository" key there), not podiumd's — podiumd's own
    values.yaml only overrides their "tag:", leaving "repository:"
    commented out for documentation.

    Resolution per path: podiumd's OWN explicit "repository:" override
    at that exact nested location wins if present (get_path(values,
    ".".join(path) + ".repository")) — checked FIRST and regardless of
    whether path[0] is even a known Chart.yaml dependency, same
    resolution order lib.image_repository_check.find_images_without_
    repository already uses, and for the same reason: podiumd's own
    values.yaml answers this directly, no dependency needed to ask it.
    Next, for a path from lib.upgradedoc.find_component_version_tags (a
    COMPONENT_VERSION_PATHS-registered bare tag/version field, never
    nested under an "image:"/"...Image:" dict with its own
    "repository:" sibling in the first place) — version_repository_
    path_for(dep["name"])'s own sibling field, when that component
    registers one (redis-operator's own "imageName:", sibling to
    "imageTag:").
    Real case this matters for: "apiproxy"/"frankgateway"/"keycloak" are
    podiumd's own directly-templated top-level blocks with no Chart.yaml
    dependency of their own at all, yet several of them alias the very
    same shared global.images.nginx anchor a real dependency's own
    "<component>.nginx.image" sidecar does — excluding them here would
    silently split one shared-image group into "the dependencies' own
    usages" (correctly grouped) plus "everyone else" (each wrongly on
    its own), the exact opposite of this function's whole purpose.

    Only once there's no own override does a known dependency matter at
    all — its vendored subchart's own default at the same relative
    location (get_path(subchart_values, ".".join(path[1:]) +
    ".repository"), via resolve_chart_values) — resolved AT MOST ONCE
    per dependency and reused across every one of its paths, the same
    caching primary_image_repositories does for its own narrower
    curated-path case. A path whose repository can't be resolved either
    way (no own override, AND either no known dependency or its
    subchart doesn't set one either) is silently skipped — not every
    image belongs to a Chart.yaml dependency at all, and not every
    image, dependency or not, has an explicit repository set anywhere
    this function can see.

    More than one path landing under the same repository is the normal,
    expected shape for a base image shared across several unrelated
    components via values.yaml's global.images anchor block (nginx,
    curl, busybox, redis — pinned once, aliased everywhere else via a
    YAML anchor/alias — see lib.image_version's own MULTIPLE_KEY
    convention for the same "one shared image, many usage sites" idea)
    — e.g. every "<component>.nginx.image" sidecar aliasing the same
    global.images.nginx anchor lands together here, all under
    "nginxinc/nginx-unprivileged".

    allow_pull defaults to False (offline-only, matching primary_image_
    repositories' own default) — a doc-consistency check has no
    business making a network pull; whatever's already vendored is what
    it works with."""
    by_values_key = {(dep.get("alias") or dep["name"]): dep for dep in deps}
    subchart_cache = {}  # dep name -> (values_or_None, error_or_None)
    groups = {}
    for path in paths:
        own_repo = get_path(values, ".".join(path) + ".repository")
        if isinstance(own_repo, str) and own_repo:
            groups.setdefault(strip_registry_host(own_repo), []).append(path)
            continue

        dep = by_values_key.get(path[0]) if path else None
        if dep is None:
            continue

        sibling_rel = version_repository_path_for(dep["name"])
        if sibling_rel:
            sibling_repo = get_path(values, f"{path[0]}.{sibling_rel}")
            if isinstance(sibling_repo, str) and sibling_repo:
                groups.setdefault(strip_registry_host(sibling_repo), []).append(path)
                continue

        if dep["name"] not in subchart_cache:
            if chart_dir is None:
                subchart_cache[dep["name"]] = (None, f"no chart_dir given — can't resolve {dep['name']}'s subchart default")
            else:
                sub_values, _source, err = resolve_chart_values(chart_dir, dep, dep["version"], allow_pull=allow_pull)
                subchart_cache[dep["name"]] = (sub_values, err)
        sub_values, _error = subchart_cache[dep["name"]]
        if sub_values is None:
            continue
        repo = get_path(sub_values, ".".join(path[1:]) + ".repository")
        if isinstance(repo, str) and repo:
            groups.setdefault(strip_registry_host(repo), []).append(path)
    return groups


def repository_path_map(chart_dir, deps, values, paths, allow_pull=False):
    """{strip_registry_host(repository): values-tree path} — paths_by_
    repository's own per-repository groups, collapsed to each group's
    single last-processed path. Exists because an images-manifest
    entry's "name:" is, under the current strip-registry convention,
    exactly a repository in this same stripped form (docs/images/acr-
    mirror-naming.md) — so this map gives an exact entry -> values-
    tree-path match, where resolve_entry_path's fuzzy name-word
    matching breaks down: a manifest name like
    "infonl/zaakafhandelcomponent" no longer resembles the values.yaml
    key ("zac") the way the old hand-translated slugs (name: "zac")
    did. A single survivor per repository is exactly right for THIS
    purpose (one entry, one path, done) — see paths_by_repository's own
    docstring for why a caller needing every path a shared repository
    covers (not just one) should use that function directly instead."""
    return {repo: repo_paths[-1] for repo, repo_paths
            in paths_by_repository(chart_dir, deps, values, paths, allow_pull=allow_pull).items()}


def canonical_sidecar_row_names(chart_dir, deps, values, paths, allow_pull=False):
    """{canonical doc-row name: values-tree path} for every image path
    that isn't a Chart.yaml dependency's own name/alias directly — the
    two other shapes update-image-version actually writes a doc row
    under (see its own update_docs_single_component/
    update_docs_shared_image):
    - "<values_key> - <basename>" for a sidecar nested under a real
      dependency (e.g. "redis-operator - redis", "redis-operator -
      redis-exporter") — `basename` is that image's own repository's
      last "/"-segment, resolved via repository_path_map (own
      override in `values` if present, else the owning dependency's
      vendored subchart default).
    - bare "<basename>" for an image pinned under the shared "global"
      top-level key (update-image-version's MULTIPLE_KEY convention —
      no single dependency owns it, so there's no "<values_key> -"
      prefix at all; its own repository is always set explicitly
      there, never a subchart-default fallback).

    A dependency's own PRIMARY image (image_paths_for) is deliberately
    excluded — match_dependency already covers that case by the
    dependency's plain name/alias, and this function exists
    specifically for what match_dependency can't reach.

    Exists so a doc row that doesn't match a real dependency can still
    be checked against a real, deterministically-computed canonical
    name — never guessed at from free-form prose (see
    resolve_entry_path's own fuzzy word-matching, which this
    deliberately does NOT reuse)."""
    by_values_key = {(dep.get("alias") or dep["name"]): dep for dep in deps}
    sidecar_paths, global_paths = [], []
    for path in paths:
        if not path:
            continue
        if path[0] == "global":
            global_paths.append(path)
            continue
        dep = by_values_key.get(path[0])
        if dep is not None and ".".join(path[1:]) not in set(image_paths_for(dep["name"])):
            sidecar_paths.append(path)

    names = {}
    for repo, path in repository_path_map(chart_dir, deps, values, sidecar_paths, allow_pull=allow_pull).items():
        basename = repo.rsplit("/", 1)[-1]
        # A self-referential name ("keycloak-operator - keycloak-operator" —
        # real case: keycloak-operator.operator.image, the operator's own
        # container, whose repo basename happens to equal the dependency's
        # own values key) is structurally indistinguishable from "this IS
        # the dependency's own row" — match_dependency already covers that
        # case via the bare dependency name. Never auto-documented under
        # the wrong (sidecar/image) template as if it were a genuinely
        # distinct nested image; register it in COMPONENT_IMAGE_PATHS (or
        # document it by hand) instead if it ever needs its own row.
        if basename.lower() == path[0].lower():
            continue
        names[f"{path[0]} - {basename}"] = path
    for path in global_paths:
        repo = get_path(values, ".".join(path) + ".repository")
        if isinstance(repo, str) and repo:
            names[strip_registry_host(repo).rsplit("/", 1)[-1]] = path
    return names


def subchart_template_text(chart_dir, dep):
    """Every file under a vendored dependency's own templates/ directory
    (same .tgz/vendoring mechanics as subchart_values), concatenated into
    one blob — a plain-text haystack for "is this values.yaml key ever
    referenced by the sub-chart's own templates at all", not a real
    template parse. None if the .tgz isn't vendored, or has no
    templates/ directory at all (an unusually-shaped chart, or a minimal
    test fixture) — callers must treat that as "can't tell" and NOT as
    "definitely unreferenced", since an empty haystack would otherwise
    make every key look unreferenced."""
    tgz_path = chart_dir / "charts" / f"{dep['name']}-{dep['version']}.tgz"
    if not tgz_path.is_file():
        return None
    prefix = f"{dep['name']}/templates/"
    try:
        with tarfile.open(tgz_path) as tar:
            members = [m for m in tar.getmembers() if m.isfile() and m.name.startswith(prefix)]
            if not members:
                return None
            parts = []
            for member in members:
                f = tar.extractfile(member)
                if f is not None:
                    parts.append(f.read().decode("utf-8", errors="replace"))
            return "\n".join(parts)
    except tarfile.TarError:
        return None


def _dependency_for_pin(lines, pin_line, deps):
    """The Chart.yaml dependency + within-component subpath (e.g. "image",
    "frontend.image") for a digest pin's "tag:" line at pin_line (1-based),
    or (None, None) if the path can't be resolved to a component at all
    (fewer than "<component>.<...>.tag" segments) or that component has no
    matching Chart.yaml dependency."""
    path = dotted_key_path(lines, pin_line - 1)
    segments = path.split(".")
    if len(segments) < 3:
        return None, None
    component, subpath = segments[0], ".".join(segments[1:-1])
    dep = find_dependency(deps, component)
    if dep is None:
        return None, None
    return dep, subpath


def subchart_default_repository(chart_dir, lines, pin_line, deps, cache=None):
    """The `repository:` a digest pin's own component defaults to via its
    subchart's baked-in values.yaml, for a pin whose "tag:" line has no
    resolvable "repository:" of its own in podiumd's values.yaml (see
    resolve_pin_repo in lib.image_digests/fix-image-digests) — the same
    value Helm merges in at render time (see subchart_values). `pin_line`
    is the pin's 1-based "tag:" line number in `lines`; `deps` is
    Chart.yaml's "dependencies" list. `cache`, if passed, is a dict shared
    across calls so multiple pins under one component don't each re-read
    that component's .tgz. Returns None if the path can't be resolved at
    all, the component has no matching Chart.yaml dependency, or the
    subchart doesn't define a default repository at that path either."""
    dep, subpath = _dependency_for_pin(lines, pin_line, deps)
    if dep is None:
        return None
    if cache is None:
        cache = {}
    if dep["name"] not in cache:
        cache[dep["name"]] = subchart_values(chart_dir, dep)
    values = cache[dep["name"]]
    if values is None:
        return None
    return get_path(values, f"{subpath}.repository")


def subchart_needs_vendoring(chart_dir, lines, pin_line, deps):
    """True if a digest pin still unresolved by subchart_default_repository
    could plausibly be resolved after a fresh `helm dependency update`:
    its component matches a Chart.yaml dependency, but the .tgz that
    dependency would vendor at the version Chart.yaml currently pins isn't
    on disk. False for a component with no matching dependency at all
    (vendoring can never help — see fix-image-digests, which uses this
    to decide whether re-vendoring is worth the cost) or one already
    vendored at the current version (nothing to gain from redoing it — it
    simply doesn't default a repository at that path)."""
    dep, _ = _dependency_for_pin(lines, pin_line, deps)
    if dep is None:
        return False
    tgz_path = chart_dir / "charts" / f"{dep['name']}-{dep['version']}.tgz"
    return not tgz_path.is_file()


def find_images(node, path=""):
    """Recursively walk a parsed values.yaml tree, yielding (path, repository,
    tag) for every dict that has both a "repository" and a "tag" key."""
    images = []
    if isinstance(node, dict):
        if "repository" in node and "tag" in node:
            repo, tag = node["repository"], node["tag"]
            if repo and tag not in (None, ""):
                images.append((path or "(root)", repo, tag))
        for key, value in node.items():
            child_path = f"{path}.{key}" if path else key
            images.extend(find_images(value, child_path))
    elif isinstance(node, list):
        for i, item in enumerate(node):
            images.extend(find_images(item, f"{path}[{i}]"))
    return images
