"""Loads change-podiumd-baseline (a hyphenated filename, not importable
normally) as a module named `cpb`."""
import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "change-podiumd-baseline"


@pytest.fixture(scope="session")
def cpb():
    loader = SourceFileLoader("change_podiumd_baseline", str(SCRIPT_PATH))
    spec = importlib.util.spec_from_file_location("change_podiumd_baseline", SCRIPT_PATH, loader=loader)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
