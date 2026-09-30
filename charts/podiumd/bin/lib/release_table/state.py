"""Value objects passed between lib.release_table_verification's checks."""

from dataclasses import dataclass
from pathlib import Path

from lib.chart.chart_yaml import ChartDependency
from lib.yaml_types import YamlMapping


@dataclass
class ComponentRef:
    """Which component a check is about.

    `scope_key` is the values.yaml key (alias, else name); `component` the
    stable identity (dependency name or bare key), used where aliases must
    not apply; `dep` is None for MULTIPLE or a component without a chart.
    """

    scope_key: str
    component: str
    dep: ChartDependency | None = None


@dataclass
class ChartState:
    """A snapshot of the chart: the working tree or the release_table baseline.

    `chart_dir` is the same either way; used only for the subchart-default
    repository fallback.
    """

    chart_dir: Path
    deps: list[ChartDependency]
    values: YamlMapping | None
    lines: list[str]


@dataclass
class Comparison:
    """Current and baseline ChartState.

    The current `lines` guard the baseline's unscoped basename fallback
    against a same-basename, different-repository collision.
    """

    current: ChartState
    baseline: ChartState | None


@dataclass
class Observed:
    """One mismatch: `target` from release-table.csv, `actual` from the chart, and `source_label` of actual."""

    target: str
    actual: str
    source_label: str
