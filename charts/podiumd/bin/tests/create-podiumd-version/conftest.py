"""Loads create-podiumd-version (a hyphenated filename, not importable
normally) as a module named `cpv`."""
import importlib.util
from importlib.machinery import SourceFileLoader
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SCRIPTS_DIR))

SCRIPT_PATH = SCRIPTS_DIR / "create-podiumd-version"


def _load_module():
    loader = SourceFileLoader("create_podiumd_version", str(SCRIPT_PATH))
    spec = importlib.util.spec_from_file_location("create_podiumd_version", SCRIPT_PATH, loader=loader)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def cpv():
    return _load_module()
