"""Loads strip-utf8-bom (a hyphenated filename, not importable normally)
as a module named `sub` so tests can call its functions directly."""
import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "strip-utf8-bom"


@pytest.fixture(scope="session")
def sub():
    loader = SourceFileLoader("strip_utf8_bom", str(SCRIPT_PATH))
    spec = importlib.util.spec_from_file_location("strip_utf8_bom", SCRIPT_PATH, loader=loader)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
