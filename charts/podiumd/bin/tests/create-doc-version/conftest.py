"""Load create-doc-version (hyphenated, not importable) as module `cdv`."""

import importlib.util

from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "create-doc-version"


@pytest.fixture(scope="session")
def cdv() -> ModuleType:
    loader = SourceFileLoader("create_doc_version", str(SCRIPT_PATH))
    spec = importlib.util.spec_from_file_location("create_doc_version", SCRIPT_PATH, loader=loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module
