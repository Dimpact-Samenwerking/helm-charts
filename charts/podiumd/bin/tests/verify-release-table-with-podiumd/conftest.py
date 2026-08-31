"""Loads verify-release-table-with-podiumd (a hyphenated filename, not
importable normally) as a module named `vrt` so tests can call its
functions directly."""
import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "verify-release-table-with-podiumd"


@pytest.fixture(scope="session")
def vrt():
    loader = SourceFileLoader("verify_release_table_with_podiumd", str(SCRIPT_PATH))
    spec = importlib.util.spec_from_file_location("verify_release_table_with_podiumd", SCRIPT_PATH, loader=loader)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
