"""Loads list-podiumd-images.py (a hyphenated filename, not importable
normally) as a module, with its module-level path constants (CHART_YAML,
VALUES_YAML, VENDORED_DIR) repointed at an isolated temp directory so tests
never read/depend on the real chart."""
import importlib.util
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "list-podiumd-images.py"


@pytest.fixture(scope="session")
def _module():
    spec = importlib.util.spec_from_file_location("list_podiumd_images", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def lpi(_module, tmp_path, monkeypatch):
    vendored_dir = tmp_path / "charts"
    vendored_dir.mkdir()
    monkeypatch.setattr(_module, "CHART_YAML", tmp_path / "Chart.yaml")
    monkeypatch.setattr(_module, "VALUES_YAML", tmp_path / "values.yaml")
    monkeypatch.setattr(_module, "VENDORED_DIR", vendored_dir)
    return _module
