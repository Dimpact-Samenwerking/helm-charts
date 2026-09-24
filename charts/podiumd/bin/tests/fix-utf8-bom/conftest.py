"""Loads fix-utf8-bom (a hyphenated filename, not importable normally)
as a module named `sub` so tests can call its functions directly."""

import importlib.util

from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "fix-utf8-bom"


@pytest.fixture(scope="session")
def sub() -> ModuleType:
    loader = SourceFileLoader("fix_utf8_bom", str(SCRIPT_PATH))
    spec = importlib.util.spec_from_file_location("fix_utf8_bom", SCRIPT_PATH, loader=loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module
