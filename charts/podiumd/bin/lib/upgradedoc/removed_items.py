"""Components and images in the baseline but no longer in the target, as -upgrade.md lists them."""

from collections.abc import Callable
from collections.abc import Mapping
from dataclasses import dataclass

from lib.chart.chart_yaml import ChartDependency
from lib.chart.values_tree_primitives import values_key_of
from lib.chart.values_tree_primitives import version_of
from lib.upgradedoc.app_version_and_image_paths import ImagePath
from lib.upgradedoc.app_version_and_image_paths import actual_app_version
from lib.upgradedoc.chart_image_index import ChartImageIndex
from lib.upgradedoc.sorting_and_ordering import component_order_key
from lib.upgradedoc.sorting_and_ordering import path_order_key
from lib.upgradedoc.sorting_and_ordering import values_key_order
from lib.upgradedoc.string_and_parsing_basics import text_names

# Sorts after its predecessor and everything nested under it.
_AFTER_PREDECESSOR = 1 << 30


@dataclass(frozen=True)
class RemovedItem:
    """One removed component (named by its values key) or sidecar/shared image (its baseline row name)."""

    name: str
    old_app: str | None
    old_chart: str | None
    order_key: tuple[int, ...]


def removed_items(target: ChartImageIndex, baseline: ChartImageIndex) -> list[RemovedItem]:
    """Every component and sidecar/shared image of `baseline` that `target` no longer has.

    A removed component is listed alone, not with its sidecars. An image is
    removed only when its repository is gone, not when it merely moved to
    another row name (e.g. a sidecar now pinned through a global image). Each
    item sorts right after its nearest baseline predecessor that the target
    still has.
    """
    removed_deps = _removed_deps(target, baseline)
    removed_images = _removed_images(target, baseline, removed_deps)
    keys = _order_keys(target, baseline, set(removed_deps) | set(removed_images))
    items = [
        RemovedItem(
            key,
            actual_app_version(baseline.values, key, dep["name"]),
            str(dep["version"]),
            keys[key],
        )
        for key, dep in removed_deps.items()
    ]
    items += [
        RemovedItem(name, version_of(tag) if (tag := baseline.paths.get(path)) else None, None, keys[name])
        for name, path in removed_images.items()
    ]
    return sorted(items, key=lambda item: item.order_key)


def removed_image_paths(target: ChartImageIndex, baseline: ChartImageIndex) -> set[ImagePath]:
    """The baseline image paths of the items removed_items lists: every image of a
    removed component whose repository the target no longer has, and each removed image."""
    removed_deps = _removed_deps(target, baseline)
    gone = _repository_gone(target, baseline)
    dep_paths = {path for path in baseline.paths if path[0] in removed_deps and gone(path)}
    return dep_paths | set(_removed_images(target, baseline, removed_deps).values())


def removed_component_image_names(target: ChartImageIndex, baseline: ChartImageIndex) -> set[str]:
    """The baseline row names of the sidecar/shared images under a removed component.

    removed_items lists the component alone, so a row or section an earlier
    bump gave one of its images is stale.
    """
    removed_deps = _removed_deps(target, baseline)
    return {name for name, path in baseline.canonical_names.items() if path[0] in removed_deps}


def _removed_images(
    target: ChartImageIndex, baseline: ChartImageIndex, removed_deps: Mapping[str, ChartDependency]
) -> dict[str, ImagePath]:
    """{baseline row name: path} of each sidecar/shared image outside a removed component whose repository is gone."""
    gone = _repository_gone(target, baseline)
    return {
        name: path
        for name, path in baseline.canonical_names.items()
        if name not in target.canonical_names and path[0] not in removed_deps and gone(path)
    }


def _removed_deps(target: ChartImageIndex, baseline: ChartImageIndex) -> dict[str, ChartDependency]:
    """{values key: baseline dependency} for each dependency the target no longer has."""
    target_keys = {values_key_of(dep) for dep in target.deps}
    return {values_key_of(dep): dep for dep in baseline.deps if values_key_of(dep) not in target_keys}


def _repository_gone(target: ChartImageIndex, baseline: ChartImageIndex) -> Callable[[ImagePath], bool]:
    """Whether a baseline path's repository is in no target repository group.

    An image that merely moved to another path (e.g. now pinned through a
    global image) keeps its repository, so it is not removed.
    """
    baseline_repo_of = {path: repo for repo, paths in baseline.repo_groups.items() for path in paths}
    return lambda path: baseline_repo_of.get(path) not in target.repo_groups


def _order_keys(target: ChartImageIndex, baseline: ChartImageIndex, removed: set[str]) -> dict[str, tuple[int, ...]]:
    """{removed name: order key}: its nearest kept baseline predecessor's target key, then after it.

    A dependency without a top-level values.yaml key sorts after every keyed one.
    """
    baseline_order = values_key_order(baseline.values)
    sequence = [
        ((baseline_order.index(key) if key in baseline_order else len(baseline_order), 0), key)
        for key in (values_key_of(dep) for dep in baseline.deps)
    ]
    sequence += [
        (path_order_key(path, baseline.deps, baseline_order, baseline.values), name)
        for name, path in baseline.canonical_names.items()
    ]
    target_order = values_key_order(target.values)
    keys: dict[str, tuple[int, ...]] = {}
    predecessor: tuple[int, ...] = (-1,)
    for position, (_key, name) in enumerate(sorted(sequence)):
        if name in removed:
            keys[name] = (*predecessor, _AFTER_PREDECESSOR, position)
        else:
            predecessor = component_order_key(name, target.deps, target_order, target.canonical_names, target.values)
    return keys


def removed_item_named(text: str, items: Mapping[str, RemovedItem]) -> RemovedItem | None:
    """The removed item a row name or "### ..." heading names: an exact name, else the only one text_names finds."""
    if text in items:
        return items[text]
    found = [name for name in items if text_names(text, name)]
    # A name inside a longer match is dropped: "foo-bar 1.0" names foo-bar, not foo.
    longest = [name for name in found if not any(other != name and text_names(other, name) for other in found)]
    return items[longest[0]] if len(longest) == 1 else None
