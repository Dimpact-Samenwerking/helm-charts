"""Load fix-oidc-url-coverage (hyphenated, not importable) as module `sub`."""

import importlib.util

from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "fix-oidc-url-coverage"


@pytest.fixture(scope="session")
def sub() -> ModuleType:
    loader = SourceFileLoader("fix_oidc_url_coverage", str(SCRIPT_PATH))
    spec = importlib.util.spec_from_file_location("fix_oidc_url_coverage", SCRIPT_PATH, loader=loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module
