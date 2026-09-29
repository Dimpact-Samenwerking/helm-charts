"""Load verify-image-version (hyphenated, not importable) as module `viv`."""

import importlib.util

from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "verify-image-version"


@pytest.fixture(scope="session")
def viv() -> ModuleType:
    loader = SourceFileLoader("verify_image_version", str(SCRIPT_PATH))
    spec = importlib.util.spec_from_file_location("verify_image_version", SCRIPT_PATH, loader=loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module
