"""The target or baseline state of the chart: its Chart.yaml dependencies and values.yaml."""

from dataclasses import dataclass

from lib.chart.chart_yaml import ChartDependency
from lib.yaml_types import YamlMapping


@dataclass
class ComponentState:
    """Target or baseline deps/values; never mixed across sides."""

    deps: list[ChartDependency]
    values: YamlMapping


@dataclass
class BaselineState:
    """deps/values at upgrade_docs_baseline. deps is None when no baseline
    was resolved: baseline comparisons are then skipped."""

    deps: list[ChartDependency] | None
    values: YamlMapping | None
