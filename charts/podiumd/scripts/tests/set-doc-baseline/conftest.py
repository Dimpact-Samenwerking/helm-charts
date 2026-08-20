"""Loads set-doc-baseline.py (a hyphenated filename, not importable
normally) as a module named `sdb` so tests can call its functions directly."""
import importlib.util
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "set-doc-baseline.py"


@pytest.fixture(scope="session")
def sdb():
    spec = importlib.util.spec_from_file_location("set_doc_baseline", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
