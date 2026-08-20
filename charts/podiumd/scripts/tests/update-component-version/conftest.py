"""Loads update-component-version.py (a hyphenated filename, not importable
normally) as a module named `ucv` so tests can call its functions directly."""
import importlib.util
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "update-component-version.py"


@pytest.fixture(scope="session")
def ucv():
    spec = importlib.util.spec_from_file_location("update_component_version", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
