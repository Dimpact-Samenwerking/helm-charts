"""Loads verify-helmchart-version (a hyphenated filename, not importable
normally) as a module named `vhcv` so tests can call its functions directly."""
import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "verify-helmchart-version"


@pytest.fixture(scope="session")
def vhcv():
    loader = SourceFileLoader("verify_helmchart_version", str(SCRIPT_PATH))
    spec = importlib.util.spec_from_file_location("verify_helmchart_version", SCRIPT_PATH, loader=loader)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
