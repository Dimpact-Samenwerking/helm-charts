"""Load fix-image-digests (hyphenated, not importable) as module `sid`."""

import importlib.util
import subprocess

from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "fix-image-digests"


@pytest.fixture(scope="session")
def sid() -> ModuleType:
    loader = SourceFileLoader("fix_image_digests", str(SCRIPT_PATH))
    spec = importlib.util.spec_from_file_location("fix_image_digests", SCRIPT_PATH, loader=loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def stub_fix_helm_doc(sid: ModuleType, monkeypatch: pytest.MonkeyPatch):
    """Stub the fix-helm-doc call after writes: a real run needs helm-docs
    and would touch the real README.md. Tests of the call override this."""
    monkeypatch.setattr(sid, "run_script", lambda cmd, *a, **k: subprocess.CompletedProcess(cmd, 0))
