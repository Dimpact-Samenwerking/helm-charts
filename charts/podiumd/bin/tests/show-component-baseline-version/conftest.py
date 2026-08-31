"""Loads show-component-baseline-version (a hyphenated filename, not
importable normally) as a module named `scbv`."""
import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "show-component-baseline-version"


@pytest.fixture(scope="session")
def scbv():
    loader = SourceFileLoader("show_component_baseline_version", str(SCRIPT_PATH))
    spec = importlib.util.spec_from_file_location("show_component_baseline_version", SCRIPT_PATH, loader=loader)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
