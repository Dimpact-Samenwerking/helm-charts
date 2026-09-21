"""Loads update-component-version (a hyphenated filename, not importable
normally) as a module named `ucv` so tests can call its functions directly.

Also provides `libcomponentdocs`/`libcomponentdocschanges` for the doc-
mutation helpers that live in lib.component_docs/lib.component_docs.
changes_section (shared with update-image-version) — ucv itself only
re-exports the ones it actually calls from its own main(); a helper
ucv's own code never calls (e.g. find_component_row, used only
internally by lib.component_docs.changes_section.update_component_table)
isn't re-exported there at all, so its own tests go through these
fixtures instead (same convention as tests/verify-podiumd/conftest.py's
lib* fixtures)."""

import importlib.util
import subprocess
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SCRIPTS_DIR))

SCRIPT_PATH = SCRIPTS_DIR / "update-component-version"

import lib.component_docs as component_docs
import lib.component_docs.changes_section as component_docs_changes_section


@pytest.fixture(scope="session")
def ucv():
    loader = SourceFileLoader("update_component_version", str(SCRIPT_PATH))
    spec = importlib.util.spec_from_file_location("update_component_version", SCRIPT_PATH, loader=loader)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def libcomponentdocs():
    return component_docs


@pytest.fixture(scope="session")
def libcomponentdocschanges():
    return component_docs_changes_section


@pytest.fixture(autouse=True)
def block_real_subprocess_calls(monkeypatch):
    """main() shells out to fix-helm-doc via subprocess.run — fake
    that (and anything else) here so a test can't accidentally run the real
    script against the real repo. git commands still run for real, since
    the hermetic tmp-repo tests (git() helper, init_git_repo) need them.
    Returns the list of commands seen, for tests that want to assert what
    main() invoked."""
    calls = []
    real_run = subprocess.run

    def fake_run(cmd, *args, **kwargs):
        calls.append(cmd)
        if cmd and cmd[0] == "git":
            return real_run(cmd, *args, **kwargs)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    return calls
