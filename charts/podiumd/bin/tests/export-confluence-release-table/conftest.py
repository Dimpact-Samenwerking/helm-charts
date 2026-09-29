"""Load export-confluence-release-table (hyphenated, not importable) as `ecrt`."""

import importlib.util
import sys

from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SCRIPTS_DIR))

SCRIPT_PATH = SCRIPTS_DIR / "export-confluence-release-table"


@pytest.fixture(scope="session")
def ecrt() -> ModuleType:
    loader = SourceFileLoader("export_confluence_release_table", str(SCRIPT_PATH))
    spec = importlib.util.spec_from_file_location("export_confluence_release_table", SCRIPT_PATH, loader=loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def isolate_chart_dir(ecrt: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point the default CHART_DIR away from the real chart, so tests don't
    depend on whatever Chart.yaml version is checked out."""
    monkeypatch.setattr(ecrt, "CHART_DIR", tmp_path)
