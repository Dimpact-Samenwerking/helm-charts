"""Loads show-component-baseline-version.py (a hyphenated filename, not
importable normally) as a module named `scbv`."""
import importlib.util
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "show-component-baseline-version.py"


@pytest.fixture(scope="session")
def scbv():
    spec = importlib.util.spec_from_file_location("show_component_baseline_version", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
