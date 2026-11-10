"""Load verify-release-table-with-podiumd (hyphenated, not importable) as `vrt`."""

import csv
import importlib.util

from collections.abc import Callable
from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType

import pytest

from tests.chart_repo import point_chart_paths

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "verify-release-table-with-podiumd"


@pytest.fixture(scope="session")
def vrt() -> ModuleType:
    loader = SourceFileLoader("verify_release_table_with_podiumd", str(SCRIPT_PATH))
    spec = importlib.util.spec_from_file_location("verify_release_table_with_podiumd", SCRIPT_PATH, loader=loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def stub_ensure_vendored_dependencies(vrt: ModuleType, monkeypatch: pytest.MonkeyPatch):
    """Stub ensure_vendored_dependencies: tests use a fake chart without
    vendored sub-charts. Guard tests restore the real one."""
    monkeypatch.setattr(vrt, "ensure_vendored_dependencies", lambda chart_dir: None)


ChartWriter = Callable[[str, str, list[str], list[dict[str, str]]], None]


def _write_chart(
    chart_dir: Path, chart_yaml: str, values: str, fieldnames: list[str], rows: list[dict[str, str]]
) -> None:
    """Chart.yaml, values.yaml and etc/release-table.csv in chart_dir."""
    release_table = chart_dir / "etc" / "release-table.csv"
    release_table.parent.mkdir(parents=True)
    (chart_dir / "Chart.yaml").write_text(chart_yaml, encoding="utf-8")
    (chart_dir / "values.yaml").write_text(values, encoding="utf-8")
    with release_table.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


@pytest.fixture
def release_table_chart(vrt: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ChartWriter:
    """Writes a chart (Chart.yaml, values.yaml, etc/release-table.csv) and points vrt's paths at it, for main()."""

    def write_chart(chart_yaml: str, values: str, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
        chart_dir = tmp_path / "chart"
        _write_chart(chart_dir, chart_yaml, values, fieldnames, rows)
        point_chart_paths(vrt, monkeypatch, chart_dir)
        monkeypatch.setattr(vrt, "RELEASE_TABLE_CSV", chart_dir / "etc" / "release-table.csv")

    return write_chart
