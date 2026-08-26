"""Loads verify-component-version.py (a hyphenated filename, not importable
normally) as a module named `vcv` so tests can call its functions directly."""
import importlib.util
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "verify-component-version.py"


@pytest.fixture(scope="session")
def vcv():
    spec = importlib.util.spec_from_file_location("verify_component_version", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
