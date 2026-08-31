"""Loads export-confluence-release-table (a hyphenated filename, not
importable normally) as a module named `ecrt` so tests can call its
functions directly."""
import importlib.util
from importlib.machinery import SourceFileLoader
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SCRIPTS_DIR))

SCRIPT_PATH = SCRIPTS_DIR / "export-confluence-release-table"


@pytest.fixture(scope="session")
def ecrt():
    loader = SourceFileLoader("export_confluence_release_table", str(SCRIPT_PATH))
    spec = importlib.util.spec_from_file_location("export_confluence_release_table", SCRIPT_PATH, loader=loader)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
