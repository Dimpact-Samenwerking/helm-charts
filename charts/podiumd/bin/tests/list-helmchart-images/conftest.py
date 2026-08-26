"""Loads list-helmchart-images.py (a hyphenated filename, not
importable normally) as a module, with its module-level CHART_YAML constant
repointed at an isolated temp file so tests never read/depend on the real
chart."""
import importlib.util
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "list-helmchart-images.py"


@pytest.fixture(scope="session")
def _module():
    spec = importlib.util.spec_from_file_location("list_helmchart_images", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def lhi(_module, tmp_path, monkeypatch):
    monkeypatch.setattr(_module, "CHART_YAML", tmp_path / "Chart.yaml")
    return _module
