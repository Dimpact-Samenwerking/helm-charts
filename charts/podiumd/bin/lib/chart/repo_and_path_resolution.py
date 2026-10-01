"""Resolve and group image repositories across the values tree, doc row names, and subchart pin defaults."""

import tarfile

from collections.abc import Collection
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from lib.chart.chart_yaml import ChartDependency
from lib.chart.nested_subchart_identity import nested_subchart_documented_image_repository
from lib.chart.nested_subchart_identity import nested_subchart_name_for
from lib.chart.nested_subchart_identity import version_repository_path_for
from lib.chart.pull_and_subchart_resolution import formatted_repo
from lib.chart.pull_and_subchart_resolution import own_full_repository
from lib.chart.pull_and_subchart_resolution import resolve_chart_values
from lib.chart.pull_and_subchart_resolution import subchart_values
from lib.chart.registered_paths import image_paths_for
from lib.chart.registered_paths import is_primary_image_path
from lib.chart.registered_paths import is_primary_rel_path
from lib.chart.registered_paths import native_component_named
from lib.chart.registered_paths import native_components
from lib.chart.values_tree_primitives import dotted_key_path
from lib.chart.values_tree_primitives import find_app_versions
from lib.chart.values_tree_primitives import find_dependency
from lib.chart.values_tree_primitives import strip_registry_host
from lib.chart.values_tree_primitives import text_at
from lib.chart.values_tree_primitives import values_key_of
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
    image_paths = image_paths_for(name, chart_dir)
    app_versions = find_app_versions(baseline_values, values_key, image_paths)
    return baseline_ref, dep, values_key, image_paths, app_versions, None


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
    same global anchors; leaving them out would split a group).

    Per path, first match wins:
    1. podiumd's own "repository:" at that path.
    2. The component's registered sibling field (redis-operator imageName).
    3. A registered nested subchart's documented default (eck-stack).
    4. The dependency's vendored subchart default, resolved once per
       dependency.
    Unresolvable paths are skipped. allow_pull defaults to False: a
    consistency check shouldn't hit the network.
    """
    by_values_key = {values_key_of(dep): dep for dep in deps}
    state = _RepoResolutionState(chart_dir, allow_pull, {}, {})
    groups: dict[str, list[tuple[str, ...]]] = {}
    for path in paths:
        dep = by_values_key.get(path[0]) if path else None
        repo = _grouped_repository_for_path(values, path, dep, state)
        if repo:
            groups.setdefault(repo, []).append(path)
    return groups


@dataclass
class _RepoResolutionState:
    """Per-call state of paths_by_repository: caches so each .tgz/nested subchart is read at most once."""

    chart_dir: Path | None
    allow_pull: bool
    subchart_cache: dict[str, tuple[YamlMapping | None, str | None]]
    nested_subchart_cache: dict[tuple[str, str], str | None]


def _grouped_repository_for_path(
    values: YamlMapping, path: tuple[str, ...], dep: ChartDependency | None, state: _RepoResolutionState
):
    """paths_by_repository's resolution chain for one path, stripped to its group key."""
    own_repo = own_full_repository(values, path)
    if own_repo is not None:
        return strip_registry_host(own_repo)
    if dep is None:
        return None
    return _grouped_repository_from_dependency(dep, path, values, state)


def repository_group_key(repository: str) -> str:
    """The group key (and images-manifest "name:") of a repository: host-qualified, then host stripped.

    "python" and "docker.io/library/python" both give "library/python";
    "mcr.microsoft.com/azure-cli" gives "azure-cli".
    """
    return strip_registry_host(formatted_repo(repository))


def _grouped_repository_from_dependency(
    dep: ChartDependency, path: tuple[str, ...], values: YamlMapping, state: _RepoResolutionState
):
    """Tiers 2-4 of _grouped_repository_for_path, for a known `dep` without an own override."""
    sibling_rel = version_repository_path_for(dep["name"], state.chart_dir)
    if sibling_rel:
        sibling_repo = text_at(values, f"{path[0]}.{sibling_rel}")
        if isinstance(sibling_repo, str) and sibling_repo:
            return repository_group_key(sibling_repo)

    nested_repo = _cached_nested_subchart_repository(dep, path, state)
    if nested_repo:
        return repository_group_key(nested_repo)

    sub_values = _cached_subchart_values(dep, state)
    if sub_values is None:
        return None
    repo = text_at(sub_values, ".".join(path[1:]) + ".repository")
    return repository_group_key(repo) if isinstance(repo, str) and repo else None


def _cached_nested_subchart_repository(dep: ChartDependency, path: tuple[str, ...], state: _RepoResolutionState):
    """dep's registered nested subchart's documented repository at `path`, cached per (dep, nested chart)."""
    nested_rel = ".".join(path[1:])
    nested_chart_name = nested_subchart_name_for(dep["name"], nested_rel, state.chart_dir)
    if not nested_chart_name:
        return None
    cache_key = (dep["name"], nested_chart_name)
    if cache_key not in state.nested_subchart_cache:
        state.nested_subchart_cache[cache_key] = (
            nested_subchart_documented_image_repository(state.chart_dir, dep, nested_chart_name)
            if state.chart_dir is not None
            else None
        )
    return state.nested_subchart_cache[cache_key]


def _cached_subchart_values(dep: ChartDependency, state: _RepoResolutionState):
    """resolve_chart_values(dep), cached per dependency."""
    if dep["name"] not in state.subchart_cache:
        if state.chart_dir is None:
            state.subchart_cache[dep["name"]] = (
                None,
                f"no chart_dir given — can't resolve {dep['name']}'s subchart default",
            )
        else:
            sub_values, _source, err = resolve_chart_values(
                state.chart_dir, dep, dep["version"], allow_pull=state.allow_pull
            )
            state.subchart_cache[dep["name"]] = (sub_values, err)
    sub_values, _error = state.subchart_cache[dep["name"]]
    return sub_values


def full_repository_for_path(
    chart_dir: Path | None,
    deps: list[ChartDependency],
    values: YamlMapping | None,
    path: tuple[str, ...],
    *,
    allow_pull: bool = False,
):
    """The fully host-qualified repository for `path`, or None; same chain as paths_by_repository.

    Registry calls and manifest "url:" need this: rebuilding a host from a
    stripped group key would wrongly assume Docker Hub.

    A sibling "registry:" that looks like a host (".", ":" or localhost,
    e.g. mi's mcr.microsoft.com) is used as-is. One that doesn't (zaakbrug's
    "registry: wearefrank") is a Docker Hub namespace and goes through
    parse_repo with the repository.
    """
    own_repo = own_full_repository(values, path)
    if own_repo is not None:
        return own_repo

    by_values_key = {values_key_of(dep): dep for dep in deps}
    dep = by_values_key.get(path[0]) if path else None
    if dep is None:
        return None
    return _full_repo_from_dependency(chart_dir, dep, path, values, allow_pull=allow_pull)


def _full_repo_from_dependency(
    chart_dir: Path | None, dep: ChartDependency, path: tuple[str, ...], values: YamlMapping | None, *, allow_pull: bool
):
    """Tiers 2-4 of full_repository_for_path, for a known `dep` without an own override."""
    sibling_rel = version_repository_path_for(dep["name"], chart_dir)
    if sibling_rel:
        sibling_repo = text_at(values, f"{path[0]}.{sibling_rel}")
        if isinstance(sibling_repo, str) and sibling_repo:
            return formatted_repo(sibling_repo)

    nested_rel = ".".join(path[1:])
    nested_chart_name = nested_subchart_name_for(dep["name"], nested_rel, chart_dir)
    if nested_chart_name and chart_dir is not None:
        nested_repo = nested_subchart_documented_image_repository(chart_dir, dep, nested_chart_name)
        if nested_repo:
            return formatted_repo(nested_repo)

    if chart_dir is None:
        return None
    sub_values, _source, _err = resolve_chart_values(chart_dir, dep, dep["version"], allow_pull=allow_pull)
    if sub_values is None:
        return None
    repo = text_at(sub_values, ".".join(path[1:]) + ".repository")
    return formatted_repo(repo) if isinstance(repo, str) and repo else None


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

    Primary images are left to match_dependency. A sidecar whose repository
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


def doc_row_name(
    chart_dir: Path,
    deps: list[ChartDependency],
    values: YamlMapping,
    path: tuple[str, ...],
    all_paths: list[tuple[str, ...]],
) -> str | None:
    """The upgrade-doc row name for the image at `path` (ending in the image key), or None.

    path[0] for a primary image, else its canonical_sidecar_row_names name,
    or the owner's row name when the repository is also an owner's primary.
    update-image-version uses this so rows match what the checks resolve.
    """
    names = canonical_sidecar_row_names(chart_dir, deps, values, all_paths)
    _sidecar_paths, _global_paths, primary_paths = _classify_image_paths(chart_dir, deps, [*all_paths, path])
    if path in primary_paths:
        return path[0]
    for group in paths_by_repository(chart_dir, deps, values, all_paths).values():
        if path in group:
            primary = next((group_path for group_path in group if group_path in primary_paths), None)
            if primary is not None:
                return primary[0]
            return next((name for name, name_path in names.items() if name_path in group), None)
    return None


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


def _dependency_for_pin(lines: list[str], pin_line: int, deps: list[ChartDependency]):
    """(dependency, subpath such as "frontend.image") for the pin "tag:" at 1-based pin_line, or (None, None)."""
    path = dotted_key_path(lines, pin_line - 1)
    segments = path.split(".")
    if len(segments) < 3:
        return None, None
    component, subpath = segments[0], ".".join(segments[1:-1])
    dep = find_dependency(deps, component)
    if dep is None:
        return None, None
    return dep, subpath


# dep name -> vendored subchart values (None: not vendored).
SubchartValuesCache = dict[str, YamlMapping | None]


def subchart_default_repository(
    chart_dir: Path,
    lines: list[str],
    pin_line: int,
    deps: list[ChartDependency],
    cache: SubchartValuesCache | None = None,
) -> str | None:
    """The subchart-default "repository:" for a digest pin with none in podiumd's values.yaml, or None.

    `pin_line` is the pin's 1-based "tag:" line; `cache` avoids re-reading
    a component's .tgz across pins.
    """
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
    return text_at(values, f"{subpath}.repository")


def subchart_needs_vendoring(chart_dir: Path, lines: list[str], pin_line: int, deps: list[ChartDependency]):
    """Whether re-vendoring could resolve this pin: its dependency's .tgz at the pinned version is missing."""
    dep, _ = _dependency_for_pin(lines, pin_line, deps)
    if dep is None:
        return False
    tgz_path = chart_dir / "charts" / f"{dep['name']}-{dep['version']}.tgz"
    return not tgz_path.is_file()
