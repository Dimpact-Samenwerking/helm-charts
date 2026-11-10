"""fix-doc-consistency's inputs: where the docs are, and the target and baseline chart states."""

from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field
from functools import cached_property
from pathlib import Path

from lib.chart.chart_state import BaselineState
from lib.chart.chart_state import ComponentState
from lib.chart.chart_yaml import ChartDependency
from lib.chart.chart_yaml import load_chart_dependencies
from lib.chart.values_tree_primitives import ValuesPath
from lib.fix_doc_consistency.manifest_entries_core import BaselineRelease
from lib.fix_doc_consistency.new_and_removed_entries import MissingEntriesContext
from lib.fix_doc_consistency.text_helpers_and_repo_rename import git_mv
from lib.release_baseline import resolve_baseline_chart_state
from lib.upgradedoc.chart_image_index import ChartImageIndex
from lib.upgradedoc.chart_image_index import StateImageIndexes
from lib.upgradedoc.removed_items import RemovedItem
from lib.upgradedoc.removed_items import removed_image_paths
from lib.upgradedoc.removed_items import removed_items
from lib.upgradedoc.resolve_component_row import ResolutionContext
from lib.upgradedoc.sorting_and_ordering import OrderingContext
from lib.yaml_types import YamlMapping
from lib.yaml_types import load_yaml_mapping


@dataclass(frozen=True)
class FixDocPaths:
    """Where fix_docs reads the chart and reads and writes the docs.

    `rename` moves a doc to its new baseline name: git mv for the real docs,
    a plain rename for a copy outside the repository.
    """

    chart_dir: Path
    doc_dir: Path
    images_dir: Path
    rename: Callable[[Path, Path], None] = field(default=git_mv)

    @property
    def chart_yaml(self) -> Path:
        """The chart's Chart.yaml."""
        return self.chart_dir / "Chart.yaml"

    @property
    def values_yaml(self) -> Path:
        """The chart's values.yaml."""
        return self.chart_dir / "values.yaml"


def load_target_state(paths: FixDocPaths):
    """(deps, values) from Chart.yaml and values.yaml on disk."""
    values = load_yaml_mapping(paths.values_yaml)
    return load_chart_dependencies(paths.chart_yaml), values


def load_baseline_state(
    paths: FixDocPaths, new_baseline: str
) -> tuple[list[ChartDependency], YamlMapping] | tuple[None, None]:
    """(deps, values) at new_baseline's git ref, or (None, None) if it does not resolve."""
    state = resolve_baseline_chart_state(paths.chart_dir, new_baseline)
    return (None, None) if state.error else (state.deps, state.values)


@dataclass(frozen=True)
class RebaseState:
    """Target/baseline versions and their dependency/values trees.

    Frozen, so the cached maps derived from it stay valid for the whole run.
    """

    paths: FixDocPaths
    target: str
    new_baseline: str
    target_deps: list[ChartDependency]
    target_values: YamlMapping
    baseline_deps: list[ChartDependency] | None
    baseline_values: YamlMapping | None

    @property
    def target_state(self) -> ComponentState:
        """Chart.yaml and values.yaml of the target."""
        return ComponentState(self.target_deps, self.target_values)

    @property
    def baseline_state(self) -> BaselineState:
        """Chart.yaml and values.yaml at the baseline."""
        return BaselineState(self.baseline_deps, self.baseline_values)

    @cached_property
    def resolution(self) -> ResolutionContext:
        """The resolve_component_row inputs every doc step shares."""
        return ResolutionContext(
            self.paths.chart_dir, self.target_state, self.baseline_state, upgrade_docs_baseline=self.new_baseline
        )

    @cached_property
    def baseline_index(self) -> ChartImageIndex | None:
        """The baseline's ChartImageIndex; None when the baseline doesn't resolve."""
        if self.baseline_deps is None:
            return None
        return ChartImageIndex(self.paths.chart_dir, self.baseline_deps, self.baseline_values)

    @cached_property
    def removed_image_paths(self) -> set[ValuesPath]:
        """removed_image_paths vs the baseline; empty when it doesn't resolve."""
        if self.baseline_index is None:
            return set()
        return removed_image_paths(self.resolution.target_index, self.baseline_index)

    @cached_property
    def image_indexes(self) -> StateImageIndexes:
        """The target index and the target deps with the baseline values, shared by the image writers."""
        return StateImageIndexes(
            self.resolution.target_index,
            ChartImageIndex(self.paths.chart_dir, self.target_deps, self.baseline_values),
        )

    @cached_property
    def missing_entries_context(self) -> MissingEntriesContext:
        """One context for every images-manifest entry pass, so its resolution is built once."""
        return MissingEntriesContext(
            self.paths.chart_dir,
            self.target_deps,
            self.target_values,
            self.baseline_values,
            allow_pull=True,
            baseline_release=BaselineRelease(self.new_baseline, self.baseline_deps),
            indexes=self.image_indexes,
        )

    @cached_property
    def removed_items_ordering(self) -> tuple[list[RemovedItem], OrderingContext]:
        """The removed items vs the baseline, and the OrderingContext that places them."""
        target = self.resolution.target_index
        items = [] if self.baseline_index is None else removed_items(target, self.baseline_index)
        removed_keys = {item.name: item.order_key for item in items}
        return items, OrderingContext(self.target_deps, self.target_values, target.canonical_names, removed_keys)
