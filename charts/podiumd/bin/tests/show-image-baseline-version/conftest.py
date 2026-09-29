"""Load show-image-baseline-version (hyphenated, not importable) as `sibv`."""

import importlib.util

from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "show-image-baseline-version"


@pytest.fixture(scope="session")
def sibv() -> ModuleType:
    loader = SourceFileLoader("show_image_baseline_version", str(SCRIPT_PATH))
    spec = importlib.util.spec_from_file_location("show_image_baseline_version", SCRIPT_PATH, loader=loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module
