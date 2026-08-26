"""Loads update-image-version.py (a hyphenated filename, not importable
normally) as a module named `uiv` so tests can call its functions/main()
directly."""
import importlib.util
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "update-image-version.py"


@pytest.fixture(scope="session")
def uiv():
    spec = importlib.util.spec_from_file_location("update_image_version_cli", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
