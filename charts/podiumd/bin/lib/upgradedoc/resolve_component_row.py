"""Build one Component-versions-table row for a dependency, native component or sidecar."""

import re

from collections.abc import Mapping
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Literal
from typing import TypedDict

from lib.chart.chart_state import BaselineState
from lib.chart.chart_state import ComponentState
from lib.chart.chart_yaml import ChartDependency
from lib.chart.historical_baselines import BaselineLookup
from lib.chart.historical_baselines import baseline_tag_for_sidecar_path
from lib.chart.historical_baselines import historical_app_version_for_path
from lib.chart.pull_and_subchart_resolution import global_image_paths
from lib.chart.registered_paths import image_paths_for
from lib.chart.registered_paths import native_components
from lib.chart.repo_and_path_resolution import paths_by_repository
from lib.chart.values_tree_primitives import dep_for_values_key
from lib.chart.values_tree_primitives import text_at
from lib.chart.values_tree_primitives import values_key_of
from lib.upgradedoc.app_version_and_image_paths import actual_app_version
from lib.upgradedoc.app_version_and_image_paths import find_image_tag_paths
from lib.upgradedoc.chart_image_index import ChartImageIndex
from lib.upgradedoc.string_and_parsing_basics import match_dependency_excluding_sidecar_names
from lib.upgradedoc.string_and_parsing_basics import match_native_component
from lib.upgradedoc.string_and_parsing_basics import normalize_version
from lib.yaml_types import YamlMapping


class UnmatchedRow(TypedDict):
    """resolve_component_row's result for a row it cannot place."""

    kind: Literal["unmatched"]


class ResolvedRow(TypedDict):
    """resolve_component_row's result for a matched row."""

    kind: Literal["sidecar", "dependency", "native"]
    dep: ChartDependency | None
    sidecar_path: tuple[str, ...] | None
    values_key: str
    top_level_key: str
    target_chart: str | None
    target_app: str | None
    baseline_resolved: bool | None
    baseline_chart: str | None
    baseline_app: str | None


@dataclass
class ResolutionContext:
    """resolve_component_row's caller-varying inputs besides the row itself.

    `baseline.deps` None skips baseline resolution: `baseline_resolved` then stays None,
    distinguishing "not requested" from "requested but unresolvable" (False)."""

    chart_dir: Path | None
    target: ComponentState
    baseline: BaselineState
    upgrade_docs_baseline: str | None = None

    @cached_property
    def target_index(self) -> ChartImageIndex:
        """The target's ChartImageIndex, built once per context: its maps are costly to build."""
        return ChartImageIndex(self.chart_dir, self.target.deps, self.target.values)


def changes_heading_has_app_version(heading: str):
    """Whether a "### ..." Changes heading shows an app-version pair.

    The app version follows the name as "<old> → <new>", "<new> (unchanged)" or "<new> (new)".
    The "(chart ...)" clause uses the same markers for the chart side, so it is stripped first:
    "openbao v2.5.5 (new) (chart 0.28.4, unchanged)". A chart-only stub heading
    ("### openbao 0.28.4") has none of the markers."""
    without_chart_clause = re.sub(r"\(chart[^)]*\)", "", heading)
    return (
        "→" in without_chart_clause
        or "->" in without_chart_clause
        or "(new)" in without_chart_clause
        or "(unchanged)" in without_chart_clause
    )


def sidecar_tag(values: YamlMapping, sidecar_path: tuple[str, ...]):
    """The tag pinned at a sidecar's values-tree path (which ends in the real image key).

    Not actual_app_version: its fallback appends ".image.tag", which picks the wrong image
    when the key isn't "image" (keycloak-operator's job pins both "image" and "initImage")."""
    tag = text_at(values, ".".join(sidecar_path) + ".tag")
    return tag.split("@", 1)[0] if isinstance(tag, str) and tag else None


@dataclass
class RowMatch:
    """Which kind of component a row identifies; at most one field is not None."""

    sidecar_path: tuple[str, ...] | None
    dep: ChartDependency | None
    native_key: str | None


def _match_row(
    row_name: str, chart_dir: Path | None, canonical_names: Mapping[str, tuple[str, ...]], deps: list[ChartDependency]
):
    """RowMatch for row_name."""
    sidecar_path = canonical_names.get(row_name)
    dep = None if sidecar_path is not None else match_dependency_excluding_sidecar_names(row_name, deps)
    # Native component: checked only once neither of the above matched.
    native_key = (
        None
        if (sidecar_path is not None or dep is not None)
        else match_native_component(row_name, native_components(chart_dir))
    )
    return RowMatch(sidecar_path, dep, native_key)


def _target_result(chart_dir: Path | None, values: YamlMapping, match: RowMatch) -> ResolvedRow:
    """resolve_component_row's result with target fields resolved and baseline fields None."""
    if match.sidecar_path is not None:
        return {
            "kind": "sidecar",
            "dep": match.dep,
            "sidecar_path": match.sidecar_path,
            "values_key": ".".join(match.sidecar_path),
            "top_level_key": match.sidecar_path[0],
            "target_chart": None,
            "target_app": sidecar_tag(values, match.sidecar_path),
            "baseline_resolved": None,
            "baseline_chart": None,
            "baseline_app": None,
        }
    if match.dep is not None:
        values_key = values_key_of(match.dep)
        return {
            "kind": "dependency",
            "dep": match.dep,
            "sidecar_path": match.sidecar_path,
            "values_key": values_key,
            "top_level_key": values_key,
            "target_chart": str(match.dep["version"]),
            "target_app": actual_app_version(values, values_key, match.dep["name"], chart_dir=chart_dir, dep=match.dep),
            "baseline_resolved": None,
            "baseline_chart": None,
            "baseline_app": None,
        }
    # Native component: no chart version; its own top-level key is also its image key.
    native_key = match.native_key
    if native_key is None:
        msg = "an unmatched row has no target result"
        raise ValueError(msg)
    return {
        "kind": "native",
        "dep": match.dep,
        "sidecar_path": match.sidecar_path,
        "values_key": native_key,
        "top_level_key": native_key,
        "target_chart": None,
        "target_app": actual_app_version(values, native_key, native_key),
        "baseline_resolved": None,
        "baseline_chart": None,
        "baseline_app": None,
    }


def _sidecar_baseline_app(resolution: ResolutionContext, sidecar_path: tuple[str, ...]) -> str | None:
    """A sidecar's baseline app version.

    Tries baseline_tag_for_sidecar_path (exact path, then same repository), then past
    images-<version>.yaml manifests."""
    chart_dir, deps, values = resolution.chart_dir, resolution.target.deps, resolution.target.values
    baseline_values = resolution.baseline.values
    baseline_paths = dict(find_image_tag_paths(baseline_values)) if baseline_values else {}
    baseline_paths.update(global_image_paths(baseline_values) if baseline_values else [])
    baseline_repo_groups = (
        paths_by_repository(chart_dir, deps, baseline_values, baseline_paths.keys()) if baseline_values else {}
    )
    baseline_app = baseline_tag_for_sidecar_path(
        BaselineLookup(chart_dir, deps, values, baseline_values, baseline_paths, baseline_repo_groups), sidecar_path
    )
    if baseline_app is None and baseline_values:
        # Not in baseline_values at all: the repository may still appear in a past
        # committed images-<version>.yaml manifest before it counts as new.
        baseline_app = historical_app_version_for_path(
            chart_dir, deps, values, sidecar_path, resolution.upgrade_docs_baseline
        )
    return baseline_app


def _historical_dependency_app(resolution: ResolutionContext, values_key: str, chart_name: str) -> str | None:
    """A dependency's or native component's app version from past images-<version>.yaml manifests, or None."""
    chart_dir, deps, values = resolution.chart_dir, resolution.target.deps, resolution.target.values
    for path in image_paths_for(chart_name, chart_dir):
        app = historical_app_version_for_path(
            chart_dir, deps, values, (values_key, *tuple(path.split("."))), resolution.upgrade_docs_baseline
        )
        if app is not None:
            return app
    return None


def _dependency_baseline_result(resolution: ResolutionContext, values_key: str, dep: ChartDependency):
    """(baseline_resolved, baseline_chart, baseline_app) for a dependency.

    baseline_resolved is whether the Chart.yaml dependency existed at the baseline ref.
    A dependency new since then still gets a baseline_app when its image is in a
    past images-<version>.yaml manifest: the image may predate the dependency."""
    baseline_dep = dep_for_values_key(resolution.baseline.deps or [], values_key)
    if baseline_dep is None:
        return False, None, _historical_dependency_app(resolution, values_key, dep["name"])
    baseline_chart = str(baseline_dep["version"])
    chart_dir = resolution.chart_dir
    baseline_values = resolution.baseline.values
    # The dependency existed at the baseline but its values.yaml image block may not have
    # (brppersonenmock), so fall back to past images-<version>.yaml manifests too.
    # Use the baseline's chart name: a chart renamed under the same alias
    # (openobject -> objecten) registers image paths under its old name.
    # With chart_dir and the baseline dep, a blank baseline tag resolves to that chart's
    # vendored appVersion (openbao's server.image.tag in 4.9.2).
    baseline_app = actual_app_version(baseline_values, values_key, baseline_dep["name"], chart_dir, baseline_dep)
    if baseline_app is None and baseline_values:
        baseline_app = _historical_dependency_app(resolution, values_key, baseline_dep["name"])
    return True, baseline_chart, baseline_app


def _native_baseline_app(resolution: ResolutionContext, native_key: str):
    """A native component's baseline app version (no dependency to check existence against)."""
    baseline_values = resolution.baseline.values
    baseline_app = actual_app_version(baseline_values, native_key, native_key)
    if baseline_app is None and baseline_values:
        baseline_app = _historical_dependency_app(resolution, native_key, native_key)
    return baseline_app


def _add_baseline_result(resolution: ResolutionContext, match: RowMatch, result: ResolvedRow):
    """Fill result's baseline fields in place; only called when resolution.baseline.deps is set."""
    if match.sidecar_path is not None:
        baseline_app = _sidecar_baseline_app(resolution, match.sidecar_path)
        result["baseline_app"] = baseline_app
        result["baseline_resolved"] = result["target_app"] is not None and baseline_app is not None
    elif match.dep is not None:
        resolved, baseline_chart, baseline_app = _dependency_baseline_result(
            resolution, result["values_key"], match.dep
        )
        result["baseline_resolved"] = resolved
        result["baseline_chart"] = baseline_chart
        result["baseline_app"] = baseline_app
    elif match.native_key is not None:
        baseline_app = _native_baseline_app(resolution, match.native_key)
        result["baseline_app"] = baseline_app
        result["baseline_resolved"] = result["target_app"] is not None and baseline_app is not None


def resolve_component_row(
    row_name: str, canonical_names: Mapping[str, tuple[str, ...]], resolution: ResolutionContext
) -> UnmatchedRow | ResolvedRow:
    """Resolve a "Component versions" row name to its component and target/baseline versions.

    The single resolver shared by fix_component_version_table and check_docs_consistency,
    so fixer and checker cannot drift apart.

    canonical_names is lib.chart.canonical_sidecar_row_names(...)'s {row name: values path} map.
    `resolution.baseline.deps = None` skips baseline resolution (`baseline_resolved` stays None).

    A None baseline_app means the component is absent from the baseline ref and is the
    authoritative "(new)" signal; images-baseline.yaml (ACR digest provenance) is never used.
    Sidecars first try the same repository elsewhere in baseline_values (the same function the
    table row uses) and past images-<version>.yaml manifests.

    Returns:
      {"kind": "unmatched"} when row_name matches no dependency, canonical sidecar name or
          native component. A sidecar-shaped name missing from canonical_names never falls
          through to a fuzzy dependency match (see match_dependency_excluding_sidecar_names).
      {"kind": "sidecar" | "dependency" | "native",
       "dep": <Chart.yaml dependency> or None (sidecar/native),
       "sidecar_path": <tuple> or None (dependency/native),
       "values_key": ..., "top_level_key": ...,
       "target_chart": ... or None (always None for sidecar/native),
       "target_app": ... or None,
       "baseline_resolved": None (baseline not requested) | bool,
       "baseline_chart": ... or None,
       "baseline_app": ... or None}"""
    match = _match_row(row_name, resolution.chart_dir, canonical_names, resolution.target.deps)
    if match.sidecar_path is None and match.dep is None and match.native_key is None:
        return {"kind": "unmatched"}

    result = _target_result(resolution.chart_dir, resolution.target.values, match)

    if resolution.baseline.deps is not None:
        resolution = ResolutionContext(
            resolution.chart_dir,
            resolution.target,
            BaselineState(resolution.baseline.deps, resolution.baseline.values or {}),
            resolution.upgrade_docs_baseline,
        )
        _add_baseline_result(resolution, match, result)

    return result


def resolved_row_unchanged(resolved: ResolvedRow) -> bool:
    """Whether a row's app and chart versions both equal the baseline's (nothing to document).

    False when the baseline was not requested or not resolved. Shared by checker and fixer."""
    if resolved["baseline_resolved"] is not True:
        return False
    return normalize_version(resolved["target_app"]) == normalize_version(resolved["baseline_app"]) and (
        normalize_version(resolved["target_chart"]) == normalize_version(resolved["baseline_chart"])
    )
