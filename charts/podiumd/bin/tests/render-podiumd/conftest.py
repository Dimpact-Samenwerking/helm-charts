"""Loads render-podiumd.py (a hyphenated filename, not importable normally)
as a module named `rp`."""
import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SCRIPTS_DIR))

SCRIPT_PATH = SCRIPTS_DIR / "render-podiumd.py"

import lib.render_scope as render_scope


def _load_module():
    spec = importlib.util.spec_from_file_location("render_podiumd", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def rp():
    return _load_module()


@pytest.fixture(scope="session")
def librenderscope():
    return render_scope
