"""Lookups of settings.yaml's component_resolution.* registrations: image/version paths, lockstep, primaries."""

from pathlib import Path
from typing import NamedTuple

from lib.chart.chart_yaml import ChartDependency
from lib.chart.paths import CHART_DIR
from lib.chart.values_tree_primitives import dep_for_values_key
from lib.chart.values_tree_primitives import same_name
from lib.chart.values_tree_primitives import values_key_of
from lib.settings import component_resolution_chart_version_lockstep_components
from lib.settings import component_resolution_default_image_paths
from lib.settings import component_resolution_embedded_version_images
from lib.settings import component_resolution_image_paths
from lib.settings import component_resolution_native_components
from lib.settings import component_resolution_version_paths
from lib.settings import component_resolution_version_repository_paths


def component_image_paths(chart_dir: Path | None = None):
    """component_resolution_image_paths; chart_dir defaults to CHART_DIR."""
    chart_dir = chart_dir or CHART_DIR
    return component_resolution_image_paths(chart_dir)


def image_paths_for(component: str, chart_dir: Path | None = None):
    """`component`'s registered image path(s), else the generic default (["image"]).

    chart_dir defaults to CHART_DIR: some callers have none in scope.
    """
    paths = component_image_paths(chart_dir)
    if component in paths:
        return paths[component]
    resolved = chart_dir or CHART_DIR
    return component_resolution_default_image_paths(resolved)


def component_version_paths(chart_dir: Path | None = None):
    """component_resolution_version_paths; chart_dir defaults to CHART_DIR."""
    chart_dir = chart_dir or CHART_DIR
    return component_resolution_version_paths(chart_dir)


def version_paths_for(component: str, chart_dir: Path | None = None):
    """`component`'s registered bare-version path(s), or []; no generic fallback makes sense for a scalar."""
    return component_version_paths(chart_dir).get(component, [])


def split_version_fields(chart_dir: Path | None = None) -> dict[str, str]:
    """{version field: repository field} of the registered split image fields, e.g.
    {"imageTag": "imageName", "initContainerImageTag": "imageName"} for redis-operator.

    A version_paths entry counts when its component's version_repository_paths
    entry is a sibling. chart_dir defaults to CHART_DIR.
    """
    chart_dir = chart_dir or CHART_DIR
    version_paths = component_resolution_version_paths(chart_dir)
    fields: dict[str, str] = {}
    for component, repository_path in component_resolution_version_repository_paths(chart_dir).items():
        parent, _, repository_field = repository_path.rpartition(".")
        for path in version_paths.get(component, []):
            path_parent, _, version_field = path.rpartition(".")
            if path_parent == parent:
                fields[version_field] = repository_field
    return fields


def native_components(chart_dir: Path | None = None):
    """component_resolution_native_components; chart_dir defaults to CHART_DIR."""
    chart_dir = chart_dir or CHART_DIR
    return component_resolution_native_components(chart_dir)


def is_native_chart_version(chart_version: str) -> bool:
    """Whether a <chart-version> argument is "native" (any case): the
    component has no Chart.yaml dependency (native_components)."""
    return same_name(chart_version.strip(), "native")


def native_component_named(chart_dir: Path, name: str) -> str | None:
    """The native_components entry equal to `name` ignoring case, or None."""
    return next((n for n in native_components(chart_dir) if same_name(n, name)), None)


def resolve_native_component(chart_dir: Path, name: str) -> str:
    """native_component_named, exiting with an error listing the native components if none matches."""
    native = native_component_named(chart_dir, name)
    if native is None:
        natives = ", ".join(sorted(native_components(chart_dir)))
        msg = (
            f"error: chart-version 'native' is only valid for a component in "
            f"settings.yaml's component_resolution.native_components ({natives}); "
            f"'{name}' isn't one — did you mean to pass its real chart version?"
        )
        raise SystemExit(msg)
    return native


def chart_version_lockstep_components(chart_dir: Path | None = None):
    """component_resolution_chart_version_lockstep_components; chart_dir defaults to CHART_DIR."""
    chart_dir = chart_dir or CHART_DIR
    return component_resolution_chart_version_lockstep_components(chart_dir)


class PinPath(NamedTuple):
    """One registered pin of a component, relative to its values key.

    `path` is the pin as chart_image_paths keys it (an image block or a bare
    version field); `version_key` is the field holding its version.
    """

    path: str
    version_key: str

    @property
    def is_image_block(self) -> bool:
        """Whether the pin is an "image:" block, rather than a bare version field."""
        return self.version_key != self.path


def pin_paths_for(component: str, chart_dir: Path | None = None) -> list[PinPath]:
    """`component`'s primary pins: its image blocks (version in ".tag"), then its bare version fields.

    The generic default image path only applies to a component with neither
    registered: redis-operator and eck-stack have no "image:" block.
    """
    version_paths = version_paths_for(component, chart_dir)
    registered_images = component_image_paths(chart_dir).get(component)
    if registered_images is not None:
        image_paths = registered_images
    elif version_paths:
        image_paths = []
    else:
        image_paths = image_paths_for(component, chart_dir)
    return [PinPath(p, f"{p}.tag") for p in image_paths] + [PinPath(p, p) for p in version_paths]


def is_primary_rel_path(owner_name: str, rel_path: str, chart_dir: Path | None = None):
    """Whether rel_path (path[1:], dotted) is one of the owner's primary image or bare-version fields.

    `owner_name` is a dependency's chart name or a native component's name.
    Bare-version fields cover apps without an "image:" block (e.g.
    redis-operator's redisOperator.imageTag, eck-stack's *.version).
    """
    return rel_path in set(image_paths_for(owner_name, chart_dir)) or rel_path in set(
        version_paths_for(owner_name, chart_dir)
    )


def is_primary_image_path(path: tuple[str, ...], deps: list[ChartDependency], chart_dir: Path | None = None):
    """Whether `path` is a dependency's primary image/version field rather than a sidecar.

    Also True for a path with no owning dependency (native components,
    apiproxy, global): with no parent it can't be a sidecar. Deliberately
    more permissive than verify-release-table-with-podiumd's is_primary_image,
    which must still tell a native component's sidecars apart; don't merge them.
    """
    if not path:
        return False
    by_values_key = {values_key_of(dep): dep for dep in deps}
    dep = by_values_key.get(path[0])
    if dep is None:
        return True
    return is_primary_rel_path(dep["name"], ".".join(path[1:]), chart_dir)


def component_chart_versions(
    chart_dir: Path | None, key: str, deps: list[ChartDependency], baseline_deps: list[ChartDependency] | None
) -> tuple[ChartDependency | None, str, str | None, str] | None:
    """(dep, chart_name, old_chart, new_chart) for values key `key`, or None if not a component.

    A native component gives (None, key, None, "-"); old_chart is None when
    the dependency is not in baseline_deps.
    """
    dep = dep_for_values_key(deps, key)
    if dep is not None:
        baseline_dep = dep_for_values_key(baseline_deps, key) if baseline_deps else None
        old_chart = str(baseline_dep["version"]) if baseline_dep else None
        return dep, dep["name"], old_chart, str(dep["version"])
    if key in native_components(chart_dir):
        return None, key, None, "-"
    return None


def embedded_version_images(chart_dir: Path | None = None):
    """component_resolution_embedded_version_images; chart_dir defaults to CHART_DIR."""
    chart_dir = chart_dir or CHART_DIR
    return component_resolution_embedded_version_images(chart_dir)
