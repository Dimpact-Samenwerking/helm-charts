"""Loads fix-image-digests (a hyphenated filename, not importable
normally) as a module named `sid` so tests can call its functions directly."""
import importlib.util
import subprocess
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "fix-image-digests"


@pytest.fixture(scope="session")
def sid():
    loader = SourceFileLoader("fix_image_digests", str(SCRIPT_PATH))
    spec = importlib.util.spec_from_file_location("fix_image_digests", SCRIPT_PATH, loader=loader)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def stub_fix_helm_doc(sid, monkeypatch):
    """main() shells out to fix-helm-doc after any real (non-dry-run)
    write — stub it here (a real regen would need a real helm-docs binary
    and would touch the actual charts/podiumd/README.md, not this test's
    tmp_path fixture values.yaml) so every existing test that doesn't
    care about this call keeps working unchanged; tests exercising the
    call itself override this via monkeypatch."""
    monkeypatch.setattr(sid, "run_script", lambda cmd, *a, **k: subprocess.CompletedProcess(cmd, 0))
