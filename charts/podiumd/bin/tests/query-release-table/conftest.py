"""Loads query-release-table (a hyphenated filename, not importable
normally) as a module named `qrt`."""
import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "query-release-table"


@pytest.fixture(scope="session")
def qrt():
    loader = SourceFileLoader("query_release_table", str(SCRIPT_PATH))
    spec = importlib.util.spec_from_file_location("query_release_table", SCRIPT_PATH, loader=loader)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
