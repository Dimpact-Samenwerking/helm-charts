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
}
DEFAULT_IMAGE_PATHS = ["image"]


def image_paths_for(component):
    return COMPONENT_IMAGE_PATHS.get(component, DEFAULT_IMAGE_PATHS)


def load_yaml(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


# A bare MAJOR.MINOR.PATCH version, exactly — e.g. podiumd's own Chart.yaml
# "version:", or a --baseline/target argument. Anything else (a suffix, a
# git ref, a flag) is rejected up front by every caller, rather than
# silently being treated as a literal version.
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


def chart_version(chart_yaml_path):
    return str(load_yaml(chart_yaml_path)["version"])


def release_baseline(chart_dir):
    """The baseline recorded in chart_dir/release-baseline by
    create-podiumd-version/change-podiumd-baseline, or None if that file
    doesn't exist yet (older releases and fresh checkouts predate it) —
    the shared read side every other script (verify-podiumd's release-
    baseline check and its Docs consistency default, create-doc-version's
    and fix-doc-baseline's default argument, change-podiumd-baseline's
    old-value display, update-component-version's and update-image-
    version's own doc updates) reads through, so they see the same value
    the same way."""
    baseline_file = chart_dir / "release-baseline"
    if not baseline_file.is_file():
        return None
    return baseline_file.read_text(encoding="utf-8").strip()


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


def verify_chart_version(dep, version):
    """The chart-existence check verify-component-version owns: pull
    `version` of `dep`, print a "Checking chart version ... [FOUND/
    MISSING]" line, and exit 1 with a FAIL message if the pull failed.
    Returns the pulled chart's own values.yaml (parsed) on success —
    verify-component-version's own app-image check needs that values.yaml
    to resolve the image repository/host, so the chart-version check
    itself lives in exactly this one place rather than being
    reimplemented."""
    chart_name = dep["name"]
    tmpdir = Path(tempfile.mkdtemp(prefix="verify-chart-version-"))
    try:
        print(f"Checking chart version {version!r} for {chart_name}:")
        ok, stderr = pull_chart(dep, version, tmpdir)
        status = "FOUND  " if ok else "MISSING"
        suffix = f"  ({stderr})" if not ok else ""
        print(f"  [{status}] {chart_name} {version}{suffix}")
        if not ok:
            print()
            print("FAIL: chart version does not exist")
            sys.exit(1)
        chart_dir = pulled_chart_dir(tmpdir)
        return yaml.safe_load((chart_dir / "values.yaml").read_text()) or {}
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


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


def subchart_values(chart_dir, dep):
    """A vendored dependency's own values.yaml (parsed), read straight out
    of its .tgz under chart_dir/charts/ — the same file Helm merges
    podiumd's own values.yaml under at render time. None if the .tgz
    isn't vendored (not pulled yet) or doesn't have the expected layout."""
    tgz_path = chart_dir / "charts" / f"{dep['name']}-{dep['version']}.tgz"
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
