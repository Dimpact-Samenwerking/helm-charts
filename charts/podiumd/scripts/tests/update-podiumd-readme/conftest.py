"""Loads update-podiumd-readme.py (a hyphenated filename, not importable
normally) as a module named `upr` so tests can call its functions directly."""
import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SCRIPTS_DIR))

SCRIPT_PATH = SCRIPTS_DIR / "update-podiumd-readme.py"


@pytest.fixture(scope="session")
def upr():
    spec = importlib.util.spec_from_file_location("update_podiumd_readme", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
