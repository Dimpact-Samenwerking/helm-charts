"""Loads fix-helm-doc (a hyphenated filename, not importable
normally) as a module named `upr` so tests can call its functions directly."""
import importlib.util
from importlib.machinery import SourceFileLoader
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SCRIPTS_DIR))

SCRIPT_PATH = SCRIPTS_DIR / "fix-helm-doc"


@pytest.fixture(scope="session")
def upr():
    loader = SourceFileLoader("fix_helm_doc", str(SCRIPT_PATH))
    spec = importlib.util.spec_from_file_location("fix_helm_doc", SCRIPT_PATH, loader=loader)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
