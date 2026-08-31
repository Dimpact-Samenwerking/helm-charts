"""Loads fix-doc-consistency (a hyphenated filename, not importable
normally) as a module named `cdb` so tests can call its functions directly."""
import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "fix-doc-consistency"


@pytest.fixture(scope="session")
def cdb():
    loader = SourceFileLoader("fix_doc_consistency", str(SCRIPT_PATH))
    spec = importlib.util.spec_from_file_location("fix_doc_consistency", SCRIPT_PATH, loader=loader)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
