"""A component's registered repository field, and reading a nested sub-subchart's vendored files."""

from pathlib import Path

from lib.chart.chart_yaml import ChartDependency
from lib.chart.vendored_files import vendored_chart_file
from lib.settings import component_resolution_version_repository_paths


def version_repository_path_for(component: str, chart_dir: Path | None):
    """settings.yaml's component_resolution.version_repository_paths entry for `component`, or None.

    Also None when chart_dir is None.
    """
    if chart_dir is None:
        return None
    return component_resolution_version_repository_paths(chart_dir).get(component)


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
