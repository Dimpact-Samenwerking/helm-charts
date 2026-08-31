"""Loads set-doc-baseline (a hyphenated filename, not importable
normally) as a module named `sdb` so tests can call its functions directly."""
import importlib.util
from importlib.machinery import SourceFileLoader
import subprocess
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "set-doc-baseline"


@pytest.fixture(scope="session")
def sdb():
    loader = SourceFileLoader("set_doc_baseline", str(SCRIPT_PATH))
    spec = importlib.util.spec_from_file_location("set_doc_baseline", SCRIPT_PATH, loader=loader)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def stub_update_podiumd_readme(sdb, monkeypatch):
    """main() unconditionally shells out to update-podiumd-readme at the
    end of a successful run (see UPDATE_README_SCRIPT) — stub just that one
    subprocess.run call (a real regen would need a real helm-docs binary
    and would touch the actual charts/podiumd/README.md, not this test's
    tmp_path fixture repo) while leaving every other subprocess.run call
    (git, primarily — every test here exercises real git against a
    hermetic temp repo) completely real."""
    real_run = subprocess.run
    target = str(sdb.UPDATE_README_SCRIPT)

    def fake_run(cmd, *args, **kwargs):
        if isinstance(cmd, (list, tuple)) and target in cmd:
            return subprocess.CompletedProcess(cmd, 0)
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", fake_run)
