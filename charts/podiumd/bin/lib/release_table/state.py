"""The value objects lib.release_table_verification's checks pass around:
which component a check is about (ComponentRef), a snapshot of the chart
(ChartState), the current and baseline snapshots together (Comparison)
and the compared pair behind one finding (Observed)."""

from dataclasses import dataclass
from pathlib import Path

from lib.chart.chart_yaml import ChartDependency
from lib.yaml_types import YamlMapping


@dataclass
class ComponentRef:
    """scope_key/component/dep travel together everywhere a check needs to
    know WHICH component it's checking and where in values.yaml its scope
    lives: `scope_key` is the human-facing values.yaml key (a dependency's
    own alias if it has one, else its name — see compare()); `component`
    is always the stable identity (a Chart.yaml dependency's own "name",
    or the bare values.yaml key for a component with no separate chart),
    used for MULTIPLE_KEY/UNKNOWN comparisons that must never follow an
    alias. `dep` is None for a component with no separate Chart.yaml
    dependency at all (MULTIPLE_KEY, or a bare top-level values.yaml key
    like frankgateway) — every check that actually needs it (a chart
    version, or the subchart-default image fallback) only ever runs where
    it's resolved."""

    scope_key: str
    component: str
    dep: ChartDependency | None = None


@dataclass
class ChartState:
    """One point-in-time snapshot of the chart this module reads pins
    from — either the CURRENT working tree (chart_dir/deps/values/lines
    as they are right now) or the release_table baseline (see
    lib.release_baseline.resolve_baseline_chart_state) resolved at some
    historical git ref. `chart_dir` is the same podiumd chart root either
    way — only ever consulted as a last resort, to resolve a component's
    primary image via its vendored subchart's own default repository
    (see primary_image_basename/check_images_source), never re-derived
    per snapshot."""

    chart_dir: Path
    deps: list[ChartDependency]
    values: YamlMapping | None
    lines: list[str]


@dataclass
class Comparison:
    """The CURRENT and release_table-baseline ChartState together — every
    *_source check needs both: the baseline state for what a row's
    source_version_* SHOULD show, and the current state's own `lines` to
    guard the baseline-side unscoped find_matches_any_tag fallback
    against a same-basename-different-repository collision (see
    check_images_source's own docstring)."""

    current: ChartState
    baseline: ChartState | None


@dataclass
class Observed:
    """The compared pair behind one mismatch finding: `target` is
    release-table.csv's own recorded value, `actual` is what's really
    pinned right now (or at the release_table baseline), `source_label`
    names WHERE `actual` came from (e.g. "Chart.yaml", "values.yaml") for
    the finding's own message text — see report_mismatch."""

    target: str
    actual: str
    source_label: str
