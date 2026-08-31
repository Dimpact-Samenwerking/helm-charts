"""Loads show-image-baseline-version (a hyphenated filename, not
importable normally) as a module named `sibv` so tests can call its
functions directly."""
import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "show-image-baseline-version"


@pytest.fixture(scope="session")
def sibv():
    loader = SourceFileLoader("show_image_baseline_version", str(SCRIPT_PATH))
    spec = importlib.util.spec_from_file_location("show_image_baseline_version", SCRIPT_PATH, loader=loader)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
