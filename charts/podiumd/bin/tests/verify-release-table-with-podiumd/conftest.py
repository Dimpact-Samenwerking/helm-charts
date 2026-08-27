"""Loads verify-release-table-with-podiumd.py (a hyphenated filename, not
importable normally) as a module named `vrt` so tests can call its
functions directly."""
import importlib.util
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "verify-release-table-with-podiumd.py"


@pytest.fixture(scope="session")
def vrt():
    spec = importlib.util.spec_from_file_location("verify_release_table_with_podiumd", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
