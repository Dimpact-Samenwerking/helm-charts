"""Loads verify-helm-secret-size (a hyphenated filename, not importable
normally) as a module named `vhss` so tests can call its functions
directly."""
import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "verify-helm-secret-size"


@pytest.fixture(scope="session")
def vhss():
    loader = SourceFileLoader("verify_helm_secret_size", str(SCRIPT_PATH))
    spec = importlib.util.spec_from_file_location("verify_helm_secret_size", SCRIPT_PATH, loader=loader)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
