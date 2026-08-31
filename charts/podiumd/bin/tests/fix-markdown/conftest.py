"""Loads fix-markdown (a hyphenated filename, not importable normally) as
a module named `sub` so tests can call its functions directly."""
import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "fix-markdown"


@pytest.fixture(scope="session")
def sub():
    loader = SourceFileLoader("fix_markdown", str(SCRIPT_PATH))
    spec = importlib.util.spec_from_file_location("fix_markdown", SCRIPT_PATH, loader=loader)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
