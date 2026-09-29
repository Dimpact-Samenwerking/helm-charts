"""Resolve a component's app version and find every image-tag/version path pinned in a values tree."""

from collections.abc import Collection
from collections.abc import Iterator
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from typing import overload

from lib.chart.chart_yaml import ChartDependency
from lib.chart.nested_subchart_identity import nested_subchart_registered_paths
from lib.chart.pull_and_subchart_resolution import subchart_app_version
from lib.chart.registered_paths import component_image_paths
from lib.chart.registered_paths import image_paths_for
from lib.chart.registered_paths import version_paths_for
from lib.chart.values_tree_primitives import get_path
from lib.chart.values_tree_primitives import text_at
from lib.chart.values_tree_primitives import values_key_of
from lib.upgradedoc.string_and_parsing_basics import normalize_version
from lib.upgradedoc.string_and_parsing_basics import words_of
from lib.yaml_types import YamlMapping
from lib.yaml_types import YamlValue
from lib.yaml_types import scalar_text


def actual_app_version(
    values: YamlMapping | None,
    values_key: str,
    component: str | None = None,
    chart_dir: Path | None = None,
    dep: ChartDependency | None = None,
) -> str | None:
    """The app version pinned for a component, or None.

    Tries, in order:
    1. image_paths_for(component) paths + ".tag" (first non-empty tag wins for
       multi-image components);
    2. version_paths_for(component) paths read as-is, for versions not in an
       "image: {tag}" block (e.g. eck-stack's "eck-elasticsearch.version");
    3. with `chart_dir` and `dep` (needs "version"), the vendored subchart's
       appVersion — only for components registered in component_image_paths(),
       where a blank tag deliberately defers to appVersion; on an unregistered
       component it may mean the image isn't used at all.

    `component` is the Chart.yaml dependency name (registries are keyed by name,
    not alias); defaults to `values_key`."""
    resolved_component = component or values_key
    for path in image_paths_for(resolved_component, chart_dir):
        tag = text_at(values, f"{values_key}.{path}.tag")
        if tag:
            return tag.split("@")[0]
    for path in version_paths_for(resolved_component, chart_dir):
        version = text_at(values, f"{values_key}.{path}")
        if isinstance(version, str) and version:
            return version.split("@")[0]
    if chart_dir is not None and dep is not None and resolved_component in component_image_paths(chart_dir):
        return subchart_app_version(chart_dir, dep)
    return None


@dataclass
class BaselineComponentQuery:
    """Inputs for resolve_baseline_component_versions."""

    baseline_values: YamlMapping | None
    baseline_dep: ChartDependency | None
    values_key: str
    image_path: str
    chart_name: str
    new_chart: str
    chart_dir: Path | None = None


def resolve_baseline_component_versions(query: BaselineComponentQuery):
    """(old_app, old_chart) at the release baseline; shared by update-image-version and update-component-version.

    baseline_dep is the component's Chart.yaml dependency at the baseline (None
    if new or native). image_path is the exact path this bump touched (may be a
    sidecar), so the baseline tag is read there directly rather than via
    actual_app_version, which only handles the primary image.

    old_app: the baseline tag; if blank and the chart version is unchanged since
    the baseline, actual_app_version's vendored-subchart fallback against a
    synthesized {"name": chart_name, "version": new_chart} dep. Not the on-disk
    dep: its version may predate this run's Chart.yaml rewrite and point at the
    wrong .tgz.

    old_chart: baseline_dep's version, but None when old_app is None so both
    cells render "(new)" instead of a fake "old → new"."""
    raw_old_chart = str(query.baseline_dep["version"]) if query.baseline_dep is not None else None
    baseline_tag = text_at(query.baseline_values, f"{query.values_key}.{query.image_path}.tag") or ""
    old_app = baseline_tag.split("@", 1)[0] or None
    if (
        old_app is None
        and query.chart_dir is not None
        and raw_old_chart is not None
        and normalize_version(raw_old_chart) == normalize_version(query.new_chart)
    ):
        old_app = actual_app_version(
            query.baseline_values,
            query.values_key,
            query.chart_name,
            chart_dir=query.chart_dir,
            dep={"name": query.chart_name, "version": query.new_chart},
        )
    old_chart = raw_old_chart if old_app is not None else None
    return old_app, old_chart


# A path into a values tree, one key (or list index, as a string) per level.
ImagePath = tuple[str, ...]


@overload
def find_image_tag_paths(
    node: YamlValue, path: ImagePath = (), *, include_null_tags: Literal[False] = False
) -> Iterator[tuple[ImagePath, str]]: ...


@overload
def find_image_tag_paths(
    node: YamlValue, path: ImagePath = (), *, include_null_tags: bool
) -> Iterator[tuple[ImagePath, str | None]]: ...


def find_image_tag_paths(
    node: YamlValue, path: ImagePath = (), *, include_null_tags: bool = False
) -> Iterator[tuple[ImagePath, str | None]]:
    """Yield (path, tag) for every "<key>: {tag: ...}" block where <key> is "image" or ends in "Image".

    The path includes that key (e.g. ("zac", "opa", "image")), so callers must use
    path[-1] rather than assume ".image.tag". Structural, so sidecars are found too.
    The "...Image" suffix rule excludes global.images.* templates (only used via
    YAML anchors), which would otherwise count as extra usages.

    include_null_tags=True also yields (path, None) for a block with a missing or
    null tag but a repository (Helm's `.tag | default .Chart.AppVersion`); callers
    resolve it via lib.chart.resolve_subchart_default. A blank-string tag is never
    yielded: that case is resolved through actual_app_version."""
    if isinstance(node, dict):
        for key, value in node.items():
            if (key == "image" or key.endswith("Image")) and isinstance(value, dict):
                tag = value.get("tag")
                tag_text = scalar_text(tag)
                if tag_text:
                    yield (*path, key), tag_text
                elif include_null_tags and tag is None and value.get("repository"):
                    yield (*path, key), None
        for key, value in node.items():
            if key == "image" or key.endswith("Image"):
                continue
            yield from find_image_tag_paths(value, (*path, str(key)), include_null_tags=include_null_tags)
    elif isinstance(node, list):
        for i, item in enumerate(node):
            yield from find_image_tag_paths(item, (*path, str(i)), include_null_tags=include_null_tags)


def find_component_version_tags(values: YamlMapping, deps: list[ChartDependency]) -> Iterator[tuple[ImagePath, str]]:
    """(path, value) for every registered bare version field pinned in `values`.

    Covers flat scalar fields find_image_tag_paths can't see (e.g.
    "redisOperator.imageTag"). Unions version_paths_for with the nested-subchart
    registry, which also lists fields excluded from the single-app-version list."""
    for dep in deps:
        values_key = values_key_of(dep)
        rels = set(version_paths_for(dep["name"])) | set(nested_subchart_registered_paths(dep["name"]))
        for rel in rels:
            value = get_path(values, f"{values_key}.{rel}")
            if isinstance(value, str) and value:
                yield tuple(values_key.split(".")) + tuple(rel.split(".")), value


def find_all_image_and_version_paths(values: YamlMapping, deps: list[ChartDependency]) -> list[tuple[ImagePath, str]]:
    """find_image_tag_paths plus find_component_version_tags: every pinned image tag and bare version.

    Use this wherever the complete set matters, e.g. detecting image changes vs baseline."""
    return list(find_image_tag_paths(values)) + list(find_component_version_tags(values, deps))


def resolve_entry_path(entry_name: str, paths: Collection[tuple[str, ...]]):
    """Match an images-manifest entry name to a values-tree path by word-split path segments.

    The innermost segment must match the entry's last word, otherwise siblings
    with a shared prefix (zac.solr-operator.solr vs ...zookeeper-operator.zookeeper)
    are indistinguishable. A trailing "image"/"...Image" segment is ignored for
    matching but kept in the returned path."""
    entry_words = words_of(entry_name)
    if not entry_words:
        return None
    norm_entry = "".join(entry_words)

    best_path, best_diff = None, None
    for path in paths:
        descriptive = path[:-1] if path and (path[-1] == "image" or path[-1].endswith("Image")) else path
        path_words = [w for segment in descriptive for w in words_of(segment)]
        if not path_words or path_words[-1] != entry_words[-1]:
            continue
        norm_path = "".join(path_words)
        if norm_path == norm_entry:
            return path
        if norm_path in norm_entry or norm_entry in norm_path:
            # closest length = least unrelated extra text pulled in by the
            # containment match
            diff = abs(len(norm_path) - len(norm_entry))
            if best_diff is None or diff < best_diff:
                best_path, best_diff = path, diff
    return best_path


def resolve_entry_image_path(
    name: str, paths: Collection[ImagePath], repo_map: Mapping[str, ImagePath] | None = None
) -> ImagePath | None:
    """Match an images-manifest entry's "name:" to a values-tree path.

    Exact repo_map lookup first; falls back to resolve_entry_path's fuzzy matching
    for entries repo_map doesn't cover (legacy slugs, sidecars without their own
    dependency)."""
    if repo_map:
        path = repo_map.get(name)
        if path is not None and path in paths:
            return path
    return resolve_entry_path(name, paths)
