"""Pull/verify/resolve a chart dependency's own vendored or pulled
version: verify_chart_version + check_image_versions (existence
checks), pull_chart/pulled_chart_dir/pull_chart_values (the actual
`helm pull` path), subchart_values/subchart_app_version/subchart_
dependencies/resolve_subchart_default/resolve_chart_values (reading
that pulled/vendored chart), primary_image_repositories/global_image_
paths (its own image repositories, whichever source resolved), and
resolved_digest_pin (an unrelated but equally small digest-pin leaf,
grouped here rather than starting its own module)."""

import shutil
import sys
import tarfile
import tempfile

from pathlib import Path

import yaml

from lib.chart.nested_subchart_identity import nested_subchart_raw_text
from lib.chart.registered_paths import image_paths_for
from lib.chart.values_tree_primitives import get_path
from lib.procutil import run
from lib.registry import parse_repo
from lib.registry import registry_tag_exists


# A BOM breaks YAML tooling that doesn't expect one. Shared by
# verify-podiumd (detects and reports it — a verify script never writes
# to a tracked file) and fix-utf8-bom (the fixer).
def resolved_digest_pin(values, path, tag, sibling_fields):
    """`tag`'s own "@sha256:<hex>" suffix if it already has one, else —
    for a path registered in `sibling_fields` (lib.settings.
    digest_pinning_exceptions(chart_dir), or an equivalent {path:
    {"sibling_field": ..., ...}} mapping) only — that same digest read
    from the path's own sibling field instead (whatever `sibling_fields`
    names it for this exact path) and combined into the usual "<tag>@
    sha256:<hex>" shape. None when neither source has a digest at all
    (an ordinary path with no "@" in its tag, or a registered path with
    no override yet in its own sibling field — inherits the vendored
    subchart's own default, not visible here).

    The sibling field's own VALUE SHAPE is not standardized across
    entries, and is used as found rather than always assuming one: the
    two keycloak paths' own "sha:" field is bare hex, no "sha256:"
    prefix of its own (see update-component-version's write_tag_and_
    sha) — but eck-operator's own "digest:" field already carries the
    full "sha256:<hex>" form (confirmed live on the real chart: "digest:
    \"sha256:b6f26137...\""). Prepending "sha256:" unconditionally would
    double it for eck-operator's own shape."""
    if "@" in tag:
        return tag
    sibling_field = sibling_fields.get(path, {}).get("sibling_field")
    if sibling_field is None:
        return None
    digest = get_path(values, ".".join(path) + f".{sibling_field}")
    if not isinstance(digest, str) or not digest:
        return None
    return f"{tag}@{digest}" if digest.startswith("sha256:") else f"{tag}@sha256:{digest}"


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
    return (chart_dir / repo[len("file://") :]).resolve()


def pull_chart(dep, version, dest):
    """Pull a chart version via helm. Returns (ok, stderr)."""
    ref, repo_url = chart_ref(dep)
    if ref is None:
        return False, (
            f"dependency '{dep['name']}' uses a local path repository ({dep['repository']}) — not fetchable remotely"
        )
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
    repository at all — e.g. component_image_paths() points somewhere this
    chart version doesn't actually have an image (wrong path, or the
    chart restructured) — since a caller can't act on zero results
    either way, and silently reporting "0 checked, all fine" would be
    misleading."""
    repos = [
        (path, repo)
        for path in image_paths
        for repo in [get_path(values, f"{path}.repository")]
        if isinstance(repo, str) and repo
    ]
    if not repos:
        raise SystemExit(
            f"error: no repository found at {', '.join(f'{p}.repository' for p in image_paths)} "
            f"— wrong path? see lib.chart.component_image_paths()"
        )

    results = []
    for path, repo in repos:
        host, repo_path = parse_repo(repo)
        exists, digest = registry_tag_exists(host, repo_path, app_version)
        results.append(
            {"path": path, "repository": repo, "host": host, "repo_path": repo_path, "exists": exists, "digest": digest}
        )
    return results


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
    for a component whose component_image_paths()-registered image path
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


def subchart_dependencies(chart_dir, dep, version=None):
    """`dep`'s own vendored Chart.yaml "dependencies" list (parsed, same
    shape as a top-level chart's own chart_yaml.get("dependencies", [])
    — each entry's own "name"/"alias"/... as declared there) — read
    straight out of its .tgz under chart_dir/charts/, same vendored-
    .tgz-only lookup subchart_values/subchart_app_version already use.
    [] if that exact version isn't vendored, its Chart.yaml can't be
    read, or it declares no dependencies of its own — never None, so a
    caller can always safely iterate it without an extra check."""
    version = version or dep["version"]
    tgz_path = chart_dir / "charts" / f"{dep['name']}-{version}.tgz"
    if not tgz_path.is_file():
        return []
    try:
        with tarfile.open(tgz_path) as tar:
            member = tar.extractfile(f"{dep['name']}/Chart.yaml")
            if member is None:
                return []
            chart_yaml = yaml.safe_load(member.read()) or {}
            return chart_yaml.get("dependencies") or []
    except (KeyError, tarfile.TarError):
        return []


def resolve_subchart_default(chart_dir, dep, chart_name, path):
    """(chart_tree_path, version) for `path` (a lib.upgradedoc.
    find_image_tag_paths result — usually from its own include_null_
    tags=True mode — over `dep`'s own vendored default values.yaml).

    chart_tree_path is the chart-tree directory (see lib.render_scope.
    rendered_chart_paths) that actually OWNS `path` — needed for the
    render-gate regardless of whether this path's own tag is a real,
    explicit one or a null/missing one (a genuinely-vendored .tgz
    doesn't mean Helm actually installs it — e.g. zaakbrug's own
    condition-disabled "staging" block). version is the EFFECTIVE
    version Helm's own ".tag | default .Chart.AppVersion" template
    convention would resolve for a null/missing "tag:" specifically —
    None when `path`'s own tag isn't null, or when it can't be resolved
    at all (nothing vendored, or no appVersion set); never fabricated.

    Usually `chart_name`/charts/`dep`'s own VALUES-KEY (`dep.get("alias")
    or dep["name"]` — Helm's own "# Source:" annotations name a chart-
    tree directory by its ALIAS when the dependency declares one, never
    the underlying chart's real name; confirmed live against the real
    chart: eck-stack, aliased "kiss-eck", renders under "podiumd/charts/
    kiss-eck/...", never "podiumd/charts/eck-stack/..." — `chart_name`,
    e.g. "podiumd", is the OUTER chart's own name, passed in rather than
    hardcoded here to keep this module free of any single chart's own
    identity) plus dep's OWN Chart.yaml appVersion — but if path[0]
    matches one of dep's OWN declared Chart.yaml dependencies (name or
    alias — see subchart_dependencies), the image actually belongs to
    THAT NESTED dependency instead: Helm resolves ITS tag against ITS
    OWN Chart.yaml, and Helm's own "# Source:" annotations always name
    the innermost chart that actually owns a template, by THAT nested
    dependency's own alias-or-name the same way — real case:
    openinwoner's own bundled "eck-operator" (a SEPARATE, same-named
    nested dependency of openinwoner's own Chart.yaml, distinct from
    the top-level "eck-operator" dependency) — so both halves come from
    the nested dependency's own files in that case, not dep's."""
    base_path = f"{chart_name}/charts/{dep.get('alias') or dep['name']}"
    nested = next(
        (d for d in subchart_dependencies(chart_dir, dep) if path and path[0] in (d.get("alias"), d["name"])), None
    )
    if nested is None:
        return base_path, subchart_app_version(chart_dir, dep)

    nested_chart_text = nested_subchart_raw_text(chart_dir, dep, nested["name"], "Chart.yaml")
    nested_chart_yaml = yaml.safe_load(nested_chart_text) if nested_chart_text else None
    version = (nested_chart_yaml or {}).get("appVersion") if nested_chart_yaml else None
    nested_key = nested.get("alias") or nested["name"]
    return f"{base_path}/charts/{nested_key}", version


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
    for path in image_paths_for(dep["name"], chart_dir):
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


def global_image_paths(values):
    """[(path, tag), ...] for every entry directly under "global.images."
    — the shared base-image anchors (nginx/curl/busybox — see the
    values.yaml comment "Shared image references, reused via YAML
    anchors") a real dependency's own sidecar OR one of podiumd's own
    orphan top-level blocks (apiproxy, frankgateway, ...) can alias via
    "<some path>.image: *nginxImage" and the like. NOT found by find_
    image_tag_paths' own generic "<key ending in Image>" structural scan
    at all — the container key here is the base image's own bare name
    ("nginx"/"curl"/"busybox"), not "...Image", and "images" (the plural
    container one level up) is deliberately excluded from that scan
    (see its own docstring) specifically so this one shared template
    block is never counted as its own separate USAGE the way every
    alias SITE already is. Exists so a caller building the images-
    manifest's own path set can ALSO consider "global.images.<name>"
    itself as a candidate — the one true source every aliasing usage
    site actually points at — alongside those usage sites, not just
    the sites on their own."""
    images = get_path(values, "global.images")
    if not isinstance(images, dict):
        return []
    return [
        (("global", "images", name), block["tag"])
        for name, block in images.items()
        if isinstance(block, dict) and block.get("tag")
    ]
