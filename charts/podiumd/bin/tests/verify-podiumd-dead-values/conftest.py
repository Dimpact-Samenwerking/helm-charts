"""Loads verify-podiumd-dead-values (a hyphenated filename, not
importable normally) as a module named `vpdv` so tests can call its
functions directly."""
import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "verify-podiumd-dead-values"


@pytest.fixture(scope="session")
def vpdv():
    loader = SourceFileLoader("verify_podiumd_dead_values", str(SCRIPT_PATH))
    spec = importlib.util.spec_from_file_location("verify_podiumd_dead_values", SCRIPT_PATH, loader=loader)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
