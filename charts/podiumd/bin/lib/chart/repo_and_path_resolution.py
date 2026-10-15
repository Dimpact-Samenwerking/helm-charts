"""Resolve and group image repositories across the values tree, doc row names, and subchart pin defaults."""

import tarfile

from collections.abc import Collection
from collections.abc import Mapping
from pathlib import Path

from lib.chart.chart_yaml import ChartDependency
from lib.chart.nested_subchart_identity import documented_repository_for_path
from lib.chart.nested_subchart_identity import version_repository_path_for
from lib.chart.pull_and_subchart_resolution import formatted_repo
from lib.chart.pull_and_subchart_resolution import own_full_repository
from lib.chart.pull_and_subchart_resolution import resolve_chart_values
from lib.chart.registered_paths import PinPath
from lib.chart.registered_paths import is_primary_image_path
from lib.chart.registered_paths import is_primary_rel_path
from lib.chart.registered_paths import native_component_named
from lib.chart.registered_paths import native_components
from lib.chart.registered_paths import pin_paths_for
from lib.chart.values_tree_primitives import dep_for_values_key
from lib.chart.values_tree_primitives import find_app_versions
from lib.chart.values_tree_primitives import find_dependency
from lib.chart.values_tree_primitives import strip_registry_host
from lib.chart.values_tree_primitives import text_at
from lib.chart.values_tree_primitives import values_key_of
from lib.registry import ImagePathTagCheck
from lib.registry import parse_repo
from lib.registry import registry_tag_exists
from lib.release_baseline import resolve_baseline_chart_state
from lib.yaml_types import YamlMapping


def component_state_at_baseline(
    chart_dir: Path, chart_dir_relpath: str, baseline: str, component: str
) -> tuple[
    str | None,
    ChartDependency | None,
    str | None,
    list[str] | None,
    list[tuple[str, str]] | None,
    str | None,
]:
    """(baseline_ref, dep, values_key, image_paths, app_versions, error) for `component` at `baseline`.

    Resolved from git history via resolve_baseline_chart_state.
    `chart_dir_relpath` is only used in the "no dependency" message. Never
    raises: on failure error is a reason without an "error: " prefix and
    the rest is None. A native component resolves with dep None and its
    name as values_key.
    """
    baseline_ref, baseline_deps, baseline_values, _baseline_lines, error = resolve_baseline_chart_state(
        chart_dir, baseline
    )
    if error:
        return None, None, None, None, None, error
    dep = find_dependency(baseline_deps, component)
    native = None if dep else native_component_named(chart_dir, component)
    name = dep["name"] if dep else native
    if not name:
        return (
            None,
            None,
            None,
            None,
            None,
            (f"no dependency named or aliased '{component}' in {chart_dir_relpath}/Chart.yaml at {baseline_ref}"),
        )
    values_key = values_key_of(dep) if dep else name
    pins = pin_paths_for(name, chart_dir)
    app_versions = find_app_versions(baseline_values, values_key, pins)
    return baseline_ref, dep, values_key, [pin.path for pin in pins], app_versions, None


def repo_group_representative(repo_paths: list[tuple[str, ...]], deps: list[ChartDependency]) -> tuple[str, ...]:
    """The representative path of a shared-repository group: the last member of the highest rank present.

    1. A "global" path: every other member is an alias of it.
    2. A dependency's registered primary image path.
    3. A path with no owning dependency (native/top-level block).
    4. A dependency's sidecar.

    E.g. keycloak.image (3, holds the anchors) beats
    keycloak-operator.operator.config.keycloakImage (4, an alias).
    """
    by_values_key = {values_key_of(dep): dep for dep in deps}

    def rank(path: tuple[str, ...]):
        if path[0] == "global":
            return 3
        dep = by_values_key.get(path[0])
        if dep is not None and is_primary_image_path(path, deps):
            return 2
        if dep is None:
            return 1
        return 0

    best = max(rank(path) for path in repo_paths)
    return [path for path in repo_paths if rank(path) == best][-1]


class RepositoryResolver:  # pylint: disable=too-few-public-methods  # one query, plus its per-tree caches
    """The fully host-qualified repository of image paths in one values tree, resolved once per path.

    Per path, first match wins:
    1. podiumd's own "repository:" at that path (with a sibling "registry:").
    2. The component's registered sibling field (redis-operator imageName).
    3. A registered nested subchart's documented default (eck-stack).
    4. The dependency's vendored subchart default.
    A path without an owning dependency only has tier 1: podiumd's own
    templates render it. Each vendored .tgz is read at most once.
    allow_pull defaults to False: a check shouldn't hit the network.
    vendored_defaults=False drops tier 4, for a tree that already holds the
    target chart's own values: the vendored .tgz is the old chart version.
    Tier 3 still reads the vendored .tgz (a nested subchart's documented
    repository isn't in the parent's values); it is the only source for
    eck-stack's elasticsearch/kibana repositories.

    A sibling "registry:" that looks like a host (".", ":" or localhost,
    e.g. mi's mcr.microsoft.com) is used as-is. One that doesn't (zaakbrug's
    "registry: wearefrank") is a Docker Hub namespace and goes through
    parse_repo with the repository.
    """

    def __init__(
        self,
        chart_dir: Path | None,
        deps: list[ChartDependency],
        values: YamlMapping | None,
        *,
        allow_pull: bool = False,
        vendored_defaults: bool = True,
    ):
        self.chart_dir = chart_dir
        self.deps = deps
        self.values = values
        self.allow_pull = allow_pull
        self.vendored_defaults = vendored_defaults
        self._by_values_key = {values_key_of(dep): dep for dep in deps}
        self._subchart_cache: dict[str, YamlMapping | None] = {}

    def full_repository(self, path: tuple[str, ...]) -> str | None:
        """The host-qualified repository of `path`, or None when no tier resolves it."""
        own_repo = own_full_repository(self.values, path)
        if own_repo is not None:
            return own_repo
        dep = self._by_values_key.get(path[0]) if path else None
        if dep is None:
            return None

        sibling_rel = version_repository_path_for(dep["name"], self.chart_dir)
        if sibling_rel:
            sibling_repo = text_at(self.values, f"{path[0]}.{sibling_rel}")
            if isinstance(sibling_repo, str) and sibling_repo:
                return formatted_repo(sibling_repo)

        nested_repo = documented_repository_for_path(self.chart_dir, self.deps, path)
        if nested_repo:
            return formatted_repo(nested_repo)
        if not self.vendored_defaults:
            return None

        sub_values = self._subchart_values(dep)
        repo = text_at(sub_values, ".".join(path[1:]) + ".repository") if sub_values is not None else None
        return formatted_repo(repo) if isinstance(repo, str) and repo else None

    def _subchart_values(self, dep: ChartDependency):
        """resolve_chart_values(dep), cached per dependency; None without chart_dir or a resolvable chart."""
        if self.chart_dir is None:
            return None
        if dep["name"] not in self._subchart_cache:
            sub_values, _source, _err = resolve_chart_values(
                self.chart_dir, dep, dep["version"], allow_pull=self.allow_pull
            )
            self._subchart_cache[dep["name"]] = sub_values
        return self._subchart_cache[dep["name"]]


def paths_by_repository(
    chart_dir: Path | None,
    deps: list[ChartDependency],
    values: YamlMapping,
    paths: Collection[tuple[str, ...]],
    *,
    allow_pull: bool = False,
) -> dict[str, list[tuple[str, ...]]]:
    """{repository_group_key(repository): [path, ...]} for every path in `paths` with a resolvable repository.

    Includes sidecars (e.g. ZAC's opa, whose repository lives only in ZAC's
    vendored values) and paths without a dependency (apiproxy etc. alias the
    same global anchors; leaving them out would split a group). Repositories
    come from RepositoryResolver; unresolvable paths are skipped.
    """
    resolver = RepositoryResolver(chart_dir, deps, values, allow_pull=allow_pull)
    groups: dict[str, list[tuple[str, ...]]] = {}
    for path in paths:
        repo = resolver.full_repository(path)
        if repo:
            groups.setdefault(repository_group_key(repo), []).append(path)
    return groups


def repository_group_key(repository: str) -> str:
    """The group key (and images-manifest "name:") of a repository: host-qualified, then host stripped.

    "python" and "docker.io/library/python" both give "library/python";
    "mcr.microsoft.com/azure-cli" gives "azure-cli".
    """
    return strip_registry_host(formatted_repo(repository))


def full_repository_for_path(
    chart_dir: Path | None,
    deps: list[ChartDependency],
    values: YamlMapping | None,
    path: tuple[str, ...],
    *,
    allow_pull: bool = False,
):
    """RepositoryResolver.full_repository of one path, or None.

    Registry calls and manifest "url:" need this: rebuilding a host from a
    stripped group key would wrongly assume Docker Hub. Resolving many
    paths of one tree: build one RepositoryResolver instead.
    """
    return RepositoryResolver(chart_dir, deps, values, allow_pull=allow_pull).full_repository(path)


def pin_repositories(
    chart_dir: Path | None, dep: ChartDependency | None, component_values: YamlMapping, pins: list[PinPath]
) -> list[tuple[str, str]]:
    """[(pin path, repository)] for the pins of one component's values tree whose repository resolves.

    `component_values` is that component's block, over the target chart's values
    when checking a bump, so the vendored (old) chart's own defaults are never
    read. A nested subchart's documented repository (eck-stack, tier 3 of
    RepositoryResolver) still comes from the vendored chart.
    `dep` None (a native component) leaves only its own "repository:".
    """
    if dep is None:
        prefix: tuple[str, ...] = ()
        resolver = RepositoryResolver(None, [], component_values)
    else:
        prefix = (values_key_of(dep),)
        resolver = RepositoryResolver(chart_dir, [dep], {prefix[0]: component_values}, vendored_defaults=False)
    return [(pin.path, repo) for pin in pins if (repo := resolver.full_repository((*prefix, *pin.path.split("."))))]


def check_image_versions(
    chart_dir: Path | None,
    dep: ChartDependency | None,
    component_values: YamlMapping,
    pins: list[PinPath],
    app_version: str,
) -> list[ImagePathTagCheck]:
    """Registry existence check of `app_version` for every pin in `pins` whose repository resolves.

    `component_values` is one component's values tree: podiumd's block over
    the target chart's values, or a native component's block (`dep` None).
    Repositories come from RepositoryResolver, as in verify-podiumd's image
    checks, so a registered sibling field (redis-operator's imageName) counts.
    Raises SystemExit when no pin resolves (wrong path or a restructured
    chart), rather than reporting "0 checked". Pins sharing a repository
    (redis-operator's imageTag and initContainerImageTag) cost one lookup.
    """
    repos = pin_repositories(chart_dir, dep, component_values, pins)
    if not repos:
        msg = (
            f"error: no repository found for {', '.join(pin.path for pin in pins)} "
            f"— wrong path? see lib.chart.registered_paths.pin_paths_for()"
        )
        raise SystemExit(msg)

    results: list[ImagePathTagCheck] = []
    lookups: dict[str, tuple[bool, str | None]] = {}
    for path, repo in repos:
        host, repo_path = parse_repo(repo)
        if repo not in lookups:
            lookups[repo] = registry_tag_exists(host, repo_path, app_version)
        exists, digest = lookups[repo]
        results.append(
            {"path": path, "repository": repo, "host": host, "repo_path": repo_path, "exists": exists, "digest": digest}
        )
    return results


def repository_path_map(
    chart_dir: Path | None,
    deps: list[ChartDependency],
    values: YamlMapping,
    paths: Collection[tuple[str, ...]],
    *,
    allow_pull: bool = False,
) -> dict[str, tuple[str, ...]]:
    """{repository_group_key(repository): representative values-tree path}.

    Manifest "name:"s are stripped repositories, so this matches entries to
    paths exactly where name-word matching fails ("infonl/zaakafhandelcomponent"
    vs "zac"). Use paths_by_repository for every path of a group.
    """
    return group_representatives(paths_by_repository(chart_dir, deps, values, paths, allow_pull=allow_pull), deps)


def group_representatives(
    repo_groups: Mapping[str, list[tuple[str, ...]]], deps: list[ChartDependency]
) -> dict[str, tuple[str, ...]]:
    """{repository: repo_group_representative of its paths} for paths_by_repository's groups."""
    return {repo: repo_group_representative(repo_paths, deps) for repo, repo_paths in repo_groups.items()}


def canonical_sidecar_row_names(
    chart_dir: Path | None,
    deps: list[ChartDependency],
    values: YamlMapping,
    paths: Collection[tuple[str, ...]],
) -> dict[str, tuple[str, ...]]:
    """{canonical doc-row name: values-tree path} for image paths that aren't a dependency's primary image.

    - "<values_key> - <image-basename>" for a sidecar of a dependency or native
      component (e.g. "redis-operator - redis-exporter").
    - "<image-basename>" for an image under "global".

    Primary images are left to match_component. A sidecar whose repository
    is also a global image or an owner's primary image is excluded, so one
    bump never gets two row names. Deterministic; no fuzzy matching.
    """
    sidecar_paths, global_paths, primary_paths = _classify_image_paths(chart_dir, deps, paths)
    covered_repos = _global_repository_set(values, global_paths) | set(
        repository_path_map(chart_dir, deps, values, primary_paths)
    )

    names: dict[str, tuple[str, ...]] = {}
    for repo, path in repository_path_map(chart_dir, deps, values, sidecar_paths).items():
        if repo in covered_repos:
            continue
        row_name = _sidecar_row_name(repo, path)
        if row_name is not None:
            names[row_name] = path
    for path in global_paths:
        repo = text_at(values, ".".join(path) + ".repository")
        if isinstance(repo, str) and repo:
            names[repository_group_key(repo).rsplit("/", 1)[-1]] = path
    return names


def _owner_name(deps: list[ChartDependency], natives: frozenset[str], path: tuple[str, ...]) -> str | None:
    """The Chart.yaml dependency name or native component (`natives`)
    that owns values-tree `path` (by its top-level key), or None."""
    dep = next((dep for dep in deps if values_key_of(dep) == path[0]), None)
    if dep is not None:
        return dep["name"]
    # A native component owns its nested sidecars too; path[0] is its name (no alias).
    return path[0] if path[0] in natives else None


def _classify_image_paths(
    chart_dir: Path | None, deps: list[ChartDependency], paths: Collection[tuple[str, ...]]
) -> tuple[list[tuple[str, ...]], list[tuple[str, ...]], list[tuple[str, ...]]]:
    """(sidecar_paths, global_paths, primary_paths) split of `paths`; ownerless paths are in none."""
    natives = native_components(chart_dir)
    sidecar_paths: list[tuple[str, ...]] = []
    global_paths: list[tuple[str, ...]] = []
    primary_paths: list[tuple[str, ...]] = []
    for path in paths:
        if not path:
            continue
        if path[0] == "global":
            global_paths.append(path)
            continue
        owner_name = _owner_name(deps, natives, path)
        if owner_name is None:
            continue
        if is_primary_rel_path(owner_name, ".".join(path[1:]), chart_dir):
            primary_paths.append(path)
        else:
            sidecar_paths.append(path)
    return sidecar_paths, global_paths, primary_paths


def _global_repository_set(values: YamlMapping, global_paths: list[tuple[str, ...]]) -> set[str]:
    """The stripped repositories of `global_paths`, excluded from sidecar row names."""
    global_repos: set[str] = set()
    for path in global_paths:
        repo = text_at(values, ".".join(path) + ".repository")
        if isinstance(repo, str) and repo:
            global_repos.add(repository_group_key(repo))
    return global_repos


def _sidecar_row_name(repo: str, path: tuple[str, ...]):
    """The "<values_key> - <image-basename>" row name for one sidecar path, or None if there is no distinct name."""
    basename = repo.rsplit("/", 1)[-1]
    if basename.lower() != path[0].lower():
        return f"{path[0]} - {basename}"
    if len(path) >= 3 and path[-2].lower() != path[0].lower():
        return f"{path[0]} - {path[-2]}"
    return None


def subchart_template_text(chart_dir: Path, dep: ChartDependency):
    """All of a vendored dependency's templates/ files concatenated, for substring checks; None if unavailable.

    Callers must read None as "can't tell", not "unreferenced".
    """
    tgz_path = chart_dir / "charts" / f"{dep['name']}-{dep['version']}.tgz"
    if not tgz_path.is_file():
        return None
    prefix = f"{dep['name']}/templates/"
    try:
        with tarfile.open(tgz_path) as tar:
            members = [m for m in tar.getmembers() if m.isfile() and m.name.startswith(prefix)]
            if not members:
                return None
            parts: list[str] = []
            for member in members:
                f = tar.extractfile(member)
                if f is not None:
                    parts.append(f.read().decode("utf-8", errors="replace"))
            return "\n".join(parts)
    except tarfile.TarError:
        return None


def subchart_needs_vendoring(chart_dir: Path, deps: list[ChartDependency], path: tuple[str, ...]):
    """Whether re-vendoring could resolve `path`: its dependency's .tgz at the pinned version is missing."""
    dep = dep_for_values_key(deps, path[0]) if path else None
    if dep is None:
        return False
    tgz_path = chart_dir / "charts" / f"{dep['name']}-{dep['version']}.tgz"
    return not tgz_path.is_file()
