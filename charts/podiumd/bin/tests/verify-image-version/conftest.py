"""Loads verify-image-version (a hyphenated filename, not importable
normally) as a module named `viv` so tests can call its functions directly."""
import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "verify-image-version"


@pytest.fixture(scope="session")
def viv():
    loader = SourceFileLoader("verify_image_version", str(SCRIPT_PATH))
    spec = importlib.util.spec_from_file_location("verify_image_version", SCRIPT_PATH, loader=loader)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
