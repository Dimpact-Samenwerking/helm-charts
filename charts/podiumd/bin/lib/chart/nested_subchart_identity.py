"""Registered nested sub-subchart mappings and reading a nested sub-subchart's vendored files."""

import re

from pathlib import Path

from lib.chart.chart_yaml import ChartDependency
from lib.chart.paths import CHART_DIR
from lib.chart.values_tree_primitives import values_key_of
from lib.chart.vendored_files import vendored_chart_file
from lib.settings import component_resolution_version_path_nested_subcharts
from lib.settings import component_resolution_version_repository_paths


def version_repository_path_for(component: str, chart_dir: Path | None):
    """settings.yaml's component_resolution.version_repository_paths entry for `component`, or None.

    Also None when chart_dir is None.
    """
    if chart_dir is None:
        return None
    return component_resolution_version_repository_paths(chart_dir).get(component)


def nested_subchart_name_for(component: str, rel_path: str, chart_dir: Path | None):
    """The nested sub-subchart registered for (`component`, `rel_path`) in settings.yaml, or None.

    Also None when chart_dir is None.
    """
    if chart_dir is None:
        return None
    return component_resolution_version_path_nested_subcharts(chart_dir).get(component, {}).get(rel_path)


def nested_subchart_registered_paths(component: str, chart_dir: Path | None = None):
    """Every relative field settings.yaml registers a nested sub-subchart for under `component`.

    Includes fields component_version_paths excludes (e.g. eck-stack's
    disabled-by-default eck-enterprise-search.version). chart_dir defaults
    to CHART_DIR because the caller chain has none in scope.
    """
    chart_dir = chart_dir or CHART_DIR
    return list(component_resolution_version_path_nested_subcharts(chart_dir).get(component, {}))


DOCUMENTED_IMAGE_RE = re.compile(r"^#\s*image:\s*([^\s:@]+)", re.MULTILINE)


def nested_subchart_raw_text(
    chart_dir: Path, dep: ChartDependency, nested_chart_name: str, filename: str, version: str | None = None
):
    """Text of charts/<nested_chart_name>/<filename> inside dep's vendored .tgz, or None if missing."""
    raw = vendored_chart_file(chart_dir, dep, f"charts/{nested_chart_name}/{filename}", version)
    if raw is None:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def nested_subchart_documented_image_repository(
    chart_dir: Path, dep: ChartDependency, nested_chart_name: str, version: str | None = None
):
    """The repository of the first "# image: <repo>[:<tag>]" comment in a nested sub-subchart's values.yaml.

    podiumd leaves "image:" unset so the ECK operator picks its default for
    "version:"; this documented example is the only record of the upstream
    repository. None if not vendored or no such comment.
    """
    text = nested_subchart_raw_text(chart_dir, dep, nested_chart_name, "values.yaml", version=version)
    if text is None:
        return None
    m = DOCUMENTED_IMAGE_RE.search(text)
    return m.group(1) if m else None


def documented_repository_for_path(chart_dir: Path | None, deps: list[ChartDependency], path: tuple[str, ...]):
    """The full, unstripped repository of a nested-subchart-registered `path`, or None.

    Unlike paths_by_repository's stripped form, usable for real registry
    calls (parse_repo/registry_tag_exists).
    """
    if not path:
        return None
    by_values_key = {values_key_of(dep): dep for dep in deps}
    dep = by_values_key.get(path[0])
    if dep is None or chart_dir is None:
        return None
    nested_chart_name = nested_subchart_name_for(dep["name"], ".".join(path[1:]), chart_dir)
    if not nested_chart_name:
        return None
    return nested_subchart_documented_image_repository(chart_dir, dep, nested_chart_name)
