"""Loads verify-component-version (a hyphenated filename, not importable
normally) as a module named `vcv` so tests can call its functions directly."""
import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "verify-component-version"


@pytest.fixture(scope="session")
def vcv():
    loader = SourceFileLoader("verify_component_version", str(SCRIPT_PATH))
    spec = importlib.util.spec_from_file_location("verify_component_version", SCRIPT_PATH, loader=loader)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
