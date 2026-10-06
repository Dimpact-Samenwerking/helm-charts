"""The image paths of one chart state and the maps derived from them, built in one place."""

from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from lib.chart.chart_yaml import ChartDependency
from lib.chart.repo_and_path_resolution import canonical_sidecar_row_names
from lib.chart.repo_and_path_resolution import group_representatives
from lib.chart.repo_and_path_resolution import paths_by_repository
from lib.upgradedoc.app_version_and_image_paths import ImagePath
from lib.upgradedoc.app_version_and_image_paths import chart_image_paths
from lib.yaml_types import YamlMapping


class ChartImageIndex:
    """chart_image_paths of one chart state plus the repository and row-name maps built from it.

    Writers and the checker take these maps from here, so they resolve
    against the same path set. Each map is computed on first use.
    """

    def __init__(self, chart_dir: Path | None, deps: list[ChartDependency], values: YamlMapping | None):
        self.chart_dir = chart_dir
        self.deps = deps
        self.values: YamlMapping = values or {}

    @cached_property
    def paths(self) -> dict[ImagePath, str]:
        """{path: tag} for every image tag, bare version field and global.images anchor."""
        return chart_image_paths(self.values, self.deps)

    @cached_property
    def repo_groups(self) -> dict[str, list[ImagePath]]:
        """paths_by_repository of `paths`."""
        return paths_by_repository(self.chart_dir, self.deps, self.values, self.paths.keys())

    @cached_property
    def repo_map(self) -> dict[str, ImagePath]:
        """{repository: representative path} of `repo_groups`."""
        return group_representatives(self.repo_groups, self.deps)

    @cached_property
    def canonical_names(self) -> dict[str, ImagePath]:
        """canonical_sidecar_row_names of `paths`: {doc row name: values path}."""
        return canonical_sidecar_row_names(self.chart_dir, self.deps, self.values, self.paths.keys())


@dataclass(frozen=True)
class StateImageIndexes:
    """The target's ChartImageIndex, and the target's dependencies with the baseline values.

    The second groups each repository where it lived in the baseline tree;
    the sidecar-row and images-manifest writers compare against it. Built
    once per run by the caller that has both trees.
    """

    target: ChartImageIndex
    baseline_values: ChartImageIndex

    @classmethod
    def build(
        cls,
        chart_dir: Path | None,
        deps: list[ChartDependency],
        values: YamlMapping | None,
        baseline_values: YamlMapping | None,
    ) -> "StateImageIndexes":
        """Both indexes from scratch, for a caller without them."""
        return cls(ChartImageIndex(chart_dir, deps, values), ChartImageIndex(chart_dir, deps, baseline_values))
