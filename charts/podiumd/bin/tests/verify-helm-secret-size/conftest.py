"""Load verify-helm-secret-size (hyphenated, not importable) as module `vhss`."""

import importlib.util

from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "verify-helm-secret-size"


@pytest.fixture(scope="session")
def vhss() -> ModuleType:
    loader = SourceFileLoader("verify_helm_secret_size", str(SCRIPT_PATH))
    spec = importlib.util.spec_from_file_location("verify_helm_secret_size", SCRIPT_PATH, loader=loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def stub_ensure_vendored_dependencies(vhss: ModuleType, monkeypatch: pytest.MonkeyPatch):
    """Stub ensure_vendored_dependencies: tests use a fake chart without
    vendored sub-charts. Guard tests restore the real one."""
    monkeypatch.setattr(vhss, "ensure_vendored_dependencies", lambda chart_dir: None)
