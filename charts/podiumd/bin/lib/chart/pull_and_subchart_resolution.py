"""Resolve a chart dependency's vendored or pulled chart: values, appVersion, image repositories, pins."""

import copy
import shutil
import sys
import tempfile

from collections.abc import Mapping
from pathlib import Path

from lib.chart.chart_yaml import ChartDependency
from lib.chart.chart_yaml import parse_chart_app_version
from lib.chart.chart_yaml import parse_chart_dependencies
from lib.chart.nested_subchart_identity import nested_subchart_raw_text
from lib.chart.registered_paths import image_paths_for
from lib.chart.values_tree_primitives import deep_merge
from lib.chart.values_tree_primitives import mapping_at
from lib.chart.values_tree_primitives import text_at
from lib.chart.values_tree_primitives import values_key_of
from lib.chart.vendored_files import vendored_chart_file
from lib.chart.vendored_files import vendored_chart_path
from lib.procutil import run
from lib.registry import ImagePathTagCheck
from lib.registry import parse_repo
from lib.registry import registry_tag_exists
from lib.settings import DigestPinningException
from lib.yaml_types import YamlMapping
from lib.yaml_types import cached_file_mapping
from lib.yaml_types import load_yaml_mapping
from lib.yaml_types import parse_yaml_mapping
from lib.yaml_types import scalar_text


def resolved_digest_pin(
    values: YamlMapping | None,
    path: tuple[str, ...],
    tag: str,
    sibling_fields: Mapping[tuple[str, ...], DigestPinningException],
) -> str | None:
    """`tag` with its digest: its own "@sha256:" suffix, or one read from a registered sibling field.

    None when neither has a digest (a registered path with an empty sibling
    field inherits the subchart default). The sibling value may be bare hex
    (keycloak "sha:") or already "sha256:<hex>" (eck-operator "digest:"),
    so the prefix is only added when missing.
    """
    if "@" in tag:
        return tag
    exception = sibling_fields.get(path)
    sibling_field = exception.get("sibling_field") if exception is not None else None
    if sibling_field is None:
        return None
    digest = text_at(values, ".".join(path) + f".{sibling_field}")
    if not isinstance(digest, str) or not digest:
        return None
    return f"{tag}@{digest}" if digest.startswith("sha256:") else f"{tag}@sha256:{digest}"


def chart_ref(dep: ChartDependency):
    """(ref, extra_repo_url_or_None) for `helm pull`; (None, None) for a file:// or missing repository."""
    repo = dep.get("repository")
    if repo is None:
        return None, None
    if repo.startswith("oci://"):
        return f"{repo}/{dep['name']}", None
    if repo.startswith("@"):
        return f"{repo[1:]}/{dep['name']}", None
    if repo.startswith(("http://", "https://")):
        return dep["name"], repo
    if repo.startswith("file://"):
        return None, None
    msg = f"error: unsupported repository scheme: {repo}"
    raise SystemExit(msg)


def local_chart_dir(chart_dir: Path, dep: ChartDependency):
    """A "file://" dependency's directory, resolved relative to chart_dir; None for other schemes."""
    repo = dep.get("repository", "")
    if not repo.startswith("file://"):
        return None
    return (chart_dir / repo[len("file://") :]).resolve()


def require_local_chart_dir(local_dir: Path, dep: ChartDependency) -> None:
    """Exit with an error when dep's "file://" directory `local_dir` does not exist."""
    if not local_dir.is_dir():
        msg = (
            f"error: dependency '{dep['name']}' declares local path repository "
            f"({dep.get('repository')}), but {local_dir} does not exist"
        )
        raise SystemExit(msg)


def pull_chart(dep: ChartDependency, version: str, dest: Path):
    """Pull a chart version via helm. Returns (ok, stderr)."""
    ref, repo_url = chart_ref(dep)
    if ref is None:
        return False, (
            f"dependency '{dep['name']}' has no remote repository "
            f"({dep.get('repository', 'none')}) — not fetchable remotely"
        )
    cmd = ["helm", "pull", ref, "--version", version, "--untar", "--untardir", str(dest)]
    if repo_url:
        cmd += ["--repo", repo_url]
    result = run(cmd, capture_output=True, text=True)
    return result.returncode == 0, result.stderr.strip()


def pulled_chart_dir(tmpdir: Path):
    """The single chart directory `helm pull --untar` produced under tmpdir."""
    chart_dirs = [p for p in Path(tmpdir).iterdir() if p.is_dir()]
    if not chart_dirs:
        msg = f"error: helm pull produced no chart directory in {tmpdir}"
        raise SystemExit(msg)
    return chart_dirs[0]


def pull_chart_values(dep: ChartDependency, version: str):
    """The parsed values.yaml of `dep` at `version`, pulled into a temp dir; exits if the pull fails."""
    tmpdir = Path(tempfile.mkdtemp(prefix="pull-chart-values-"))
    try:
        ok, stderr = pull_chart(dep, version, tmpdir)
        if not ok:
            msg = f"error: could not pull {dep['name']} {version}: {stderr}"
            raise SystemExit(msg)
        chart_dir = pulled_chart_dir(tmpdir)
        return load_yaml_mapping(chart_dir / "values.yaml")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def verify_chart_version(chart_dir: Path, dep: ChartDependency, version: str):
    """Print a FOUND/MISSING line for `dep` at `version` and exit 1 if missing.

    Prefers a vendored .tgz over `helm pull` (see resolve_chart_values).
    Returns the chart's parsed values.yaml, needed for the image check.
    """
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


def native_component_values(chart_dir: Path, name: str) -> YamlMapping:
    """The values.yaml block of chart-less component `name` (see native_components); {} if absent."""
    return mapping_at(load_yaml_mapping(chart_dir / "values.yaml"), name)


def formatted_repo(repo: str):
    """`repo` fully host-qualified via parse_repo (Docker Hub when no host)."""
    host, repo_path = parse_repo(repo)
    return f"{host}/{repo_path}"


def own_full_repository(values: YamlMapping | None, path: tuple[str, ...]):
    """The host-qualified repository of the image block at `path`, honouring a sibling "registry:"; or None.

    First tier of full_repository_for_path.
    """
    own_repo = text_at(values, ".".join(path) + ".repository")
    if not (isinstance(own_repo, str) and own_repo):
        return None
    registry = text_at(values, ".".join(path) + ".registry")
    if isinstance(registry, str) and registry:
        registry_head = registry.partition("/")[0]
        if "." in registry_head or ":" in registry_head or registry_head == "localhost":
            return f"{registry}/{own_repo}"
        return formatted_repo(f"{registry}/{own_repo}")
    return formatted_repo(own_repo)


def component_check_values(chart_values: YamlMapping, component_values: YamlMapping | None) -> YamlMapping:
    """A copy of `chart_values` with podiumd's block for the component merged on top, as Helm layers them."""
    merged = copy.deepcopy(chart_values)
    deep_merge(merged, component_values or {})
    return merged


def check_image_versions(values: YamlMapping, image_paths: list[str], app_version: str) -> list[ImagePathTagCheck]:
    """Registry existence check of `app_version` for every path in `image_paths` with a "repository:".

    Raises SystemExit when no path has a repository (wrong path or a
    restructured chart), rather than reporting "0 checked".
    """
    repos = [
        (path, repo)
        for path in image_paths
        for repo in [own_full_repository(values, tuple(path.split(".")))]
        if repo is not None
    ]
    if not repos:
        msg = (
            f"error: no repository found at {', '.join(f'{p}.repository' for p in image_paths)} "
            f"— wrong path? see lib.chart.component_image_paths()"
        )
        raise SystemExit(msg)

    results: list[ImagePathTagCheck] = []
    for path, repo in repos:
        host, repo_path = parse_repo(repo)
        exists, digest = registry_tag_exists(host, repo_path, app_version)
        results.append(
            {"path": path, "repository": repo, "host": host, "repo_path": repo_path, "exists": exists, "digest": digest}
        )
    return results


def print_image_version_results(results: list[ImagePathTagCheck], app_version: str) -> bool:
    """Print a FOUND/MISSING line per result; True when every image version exists."""
    for r in results:
        status = "FOUND  " if r["exists"] else "MISSING"
        suffix = f"  digest={r['digest']}" if r["digest"] else ""
        print(f"  [{status}] {r['host']}/{r['repo_path']}:{app_version}{suffix}")
    return all(r["exists"] for r in results)


def subchart_values(chart_dir: Path, dep: ChartDependency, version: str | None = None):
    """A vendored dependency's parsed values.yaml at `version` (default: pinned), or None if not vendored.

    Parsed once per archive; returns a copy because callers merge into it.
    """
    tgz_path = vendored_chart_path(chart_dir, dep, version)
    if not tgz_path.is_file():
        return None

    def parse() -> YamlMapping | None:
        raw = vendored_chart_file(chart_dir, dep, "values.yaml", version)
        return None if raw is None else parse_yaml_mapping(raw.decode("utf-8"), f"{dep['name']} values.yaml")

    return copy.deepcopy(cached_file_mapping(tgz_path, "values.yaml", parse))


def subchart_app_version(chart_dir: Path, dep: ChartDependency, version: str | None = None):
    """A vendored dependency's Chart.yaml "appVersion", or None if unavailable.

    The version a template's `.tag | default .Chart.AppVersion` falls back to
    when podiumd leaves "tag:" blank (e.g. openbao server.image.tag).
    Vendored only, no pull.
    """
    raw = vendored_chart_file(chart_dir, dep, "Chart.yaml", version)
    return None if raw is None else parse_chart_app_version(raw.decode("utf-8"), f"{dep['name']} Chart.yaml")


def subchart_dependencies(chart_dir: Path, dep: ChartDependency, version: str | None = None):
    """`dep`'s vendored Chart.yaml "dependencies" list; [] (never None) if unavailable or empty."""
    raw = vendored_chart_file(chart_dir, dep, "Chart.yaml", version)
    return [] if raw is None else parse_chart_dependencies(raw.decode("utf-8"), f"{dep['name']} Chart.yaml")


def resolve_subchart_default(chart_dir: Path, dep: ChartDependency, chart_name: str, path: tuple[str, ...]):
    """(chart_tree_path, version) for image `path` in `dep`'s vendored default values.

    chart_tree_path is the chart-tree directory owning `path`, for the
    render gate (a vendored chart may still be condition-disabled). It uses
    the alias, as Helm's "# Source:" annotations do (eck-stack renders as
    kiss-eck). version is the appVersion a null/missing "tag:" resolves to,
    or None.

    If path[0] names one of dep's own nested dependencies (e.g.
    openinwoner's bundled eck-operator), both come from that nested chart.
    """
    base_path = f"{chart_name}/charts/{dep.get('alias') or dep['name']}"
    nested = next(
        (d for d in subchart_dependencies(chart_dir, dep) if path and path[0] in (d.get("alias"), d["name"])), None
    )
    if nested is None:
        return base_path, subchart_app_version(chart_dir, dep)

    nested_chart_text = nested_subchart_raw_text(chart_dir, dep, nested["name"], "Chart.yaml")
    version = parse_chart_app_version(nested_chart_text, f"{nested['name']} Chart.yaml") if nested_chart_text else None
    nested_key = values_key_of(nested)
    return f"{base_path}/charts/{nested_key}", version


def resolve_chart_values(chart_dir: Path, dep: ChartDependency, version: str, *, allow_pull: bool = True):
    """(values, source, error) for `dep` at `version`: vendored .tgz first, else `helm pull` if allowed.

    source is "vendored" or "pulled". On failure values and source are None
    and error is a reason without an "error: " prefix.
    """
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
        return load_yaml_mapping(pulled_dir / "values.yaml"), "pulled", None
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def primary_image_repositories(
    chart_dir: Path | None,
    dep: ChartDependency,
    own_values: YamlMapping | None,
    version: str | None = None,
    *,
    allow_pull: bool = True,
) -> tuple[dict[str, str | None], str | None]:
    """({path: repository_or_None}, error_or_None) for each of dep's primary image paths.

    podiumd's own "repository:" override wins; otherwise the subchart
    default at `version`, resolved at most once. error is None when every
    path had an override. chart_dir None counts as "not vendored, no pull".
    """
    values_key = values_key_of(dep)
    version = version or dep["version"]
    results: dict[str, str | None] = {}
    subchart_state: tuple[YamlMapping | None, str | None] | None = (
        None  # lazily filled on first path that needs it: (values_or_None, error_or_None)
    )
    for path in image_paths_for(dep["name"], chart_dir):
        repo = text_at(own_values, f"{values_key}.{path}.repository")
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
        results[path] = text_at(values, f"{path}.repository") if values is not None else None
    error = subchart_state[1] if subchart_state is not None else None
    return results, error


def global_image_paths(values: YamlMapping) -> list[tuple[tuple[str, ...], str]]:
    """[(path, tag), ...] for every entry directly under global.images.

    These shared anchors are skipped by find_image_tag_paths' "...Image"
    scan (so they aren't counted as a usage), but callers need them as
    candidates alongside their alias sites.
    """
    return [
        (("global", "images", name), tag)
        for name, block in mapping_at(values, "global.images").items()
        if isinstance(block, dict) and (tag := scalar_text(block.get("tag")))
    ]
