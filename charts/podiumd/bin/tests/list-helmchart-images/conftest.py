"""Loads list-helmchart-images (a hyphenated filename, not
importable normally) as a module, with its module-level CHART_YAML constant
repointed at an isolated temp file so tests never read/depend on the real
chart."""
import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "list-helmchart-images"


@pytest.fixture(scope="session")
def _module():
    loader = SourceFileLoader("list_helmchart_images", str(SCRIPT_PATH))
    spec = importlib.util.spec_from_file_location("list_helmchart_images", SCRIPT_PATH, loader=loader)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def lhi(_module, tmp_path, monkeypatch):
    monkeypatch.setattr(_module, "CHART_YAML", tmp_path / "Chart.yaml")
    return _module
