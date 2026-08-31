"""Loads update-component-version (a hyphenated filename, not importable
normally) as a module named `ucv` so tests can call its functions directly.

Also provides `libcomponentdocs` for the doc-mutation helpers that now
live in lib.component_docs (shared with update-image-version) —
ucv itself only re-exports the ones it actually calls from its own
main(); a helper ucv's own code never calls (e.g. find_component_row,
used only internally by lib.component_docs.update_component_table) isn't
re-exported there at all, so its own tests go through libcomponentdocs
instead (same convention as tests/verify-podiumd/conftest.py's lib*
fixtures)."""
import importlib.util
from importlib.machinery import SourceFileLoader
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SCRIPTS_DIR))

SCRIPT_PATH = SCRIPTS_DIR / "update-component-version"

import lib.component_docs as component_docs


@pytest.fixture(scope="session")
def ucv():
    loader = SourceFileLoader("update_component_version", str(SCRIPT_PATH))
    spec = importlib.util.spec_from_file_location("update_component_version", SCRIPT_PATH, loader=loader)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def libcomponentdocs():
    return component_docs
