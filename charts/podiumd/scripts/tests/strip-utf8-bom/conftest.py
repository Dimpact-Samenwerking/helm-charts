"""Loads strip-utf8-bom.py (a hyphenated filename, not importable normally)
as a module named `sub` so tests can call its functions directly."""
import importlib.util
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "strip-utf8-bom.py"


@pytest.fixture(scope="session")
def sub():
    spec = importlib.util.spec_from_file_location("strip_utf8_bom", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
