"""Loads query-release-table.py (a hyphenated filename, not importable
normally) as a module named `qrt`."""
import importlib.util
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "query-release-table.py"


@pytest.fixture(scope="session")
def qrt():
    spec = importlib.util.spec_from_file_location("query_release_table", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
