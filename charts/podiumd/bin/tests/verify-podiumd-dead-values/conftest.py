"""Load verify-podiumd-dead-values (hyphenated, not importable) as module `vpdv`."""

import importlib.util

from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "verify-podiumd-dead-values"


@pytest.fixture(scope="session")
def vpdv() -> ModuleType:
    loader = SourceFileLoader("verify_podiumd_dead_values", str(SCRIPT_PATH))
    spec = importlib.util.spec_from_file_location("verify_podiumd_dead_values", SCRIPT_PATH, loader=loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def stub_ensure_vendored_dependencies(vpdv: ModuleType, monkeypatch: pytest.MonkeyPatch):
    """Stub ensure_vendored_dependencies: tests use a fake chart without
    vendored sub-charts. Guard tests restore the real one."""
    monkeypatch.setattr(vpdv, "ensure_vendored_dependencies", lambda chart_dir: None)
