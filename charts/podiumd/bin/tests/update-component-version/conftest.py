"""Loads update-component-version (a hyphenated filename, not importable
normally) as a module named `ucv` so tests can call its functions directly.

Also provides `libcomponentdocschanges`/`libcomponentdocsentries` for the
doc-mutation helpers that live in lib.component_docs.changes_section/
lib.component_docs.images_manifest_entries (shared with update-image-
version) — ucv itself only re-exports the ones it actually calls from its
own main(); a helper ucv's own code never calls (e.g. find_component_row,
used only internally by lib.component_docs.changes_section.update_
component_table) isn't re-exported there at all, so its own tests go
through these fixtures instead (same convention as tests/verify-podiumd/
conftest.py's lib* fixtures)."""

import importlib.util
import subprocess
import sys

from importlib.machinery import SourceFileLoader
from pathlib import Path
from types import ModuleType

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SCRIPTS_DIR))

SCRIPT_PATH = SCRIPTS_DIR / "update-component-version"

import lib.component_docs.changes_section as component_docs_changes_section
import lib.component_docs.images_manifest_entries as component_docs_images_manifest_entries


@pytest.fixture(scope="session")
def ucv() -> ModuleType:
    loader = SourceFileLoader("update_component_version", str(SCRIPT_PATH))
    spec = importlib.util.spec_from_file_location("update_component_version", SCRIPT_PATH, loader=loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def libcomponentdocschanges() -> ModuleType:
    return component_docs_changes_section


@pytest.fixture(scope="session")
def libcomponentdocsentries() -> ModuleType:
    return component_docs_images_manifest_entries


@pytest.fixture(autouse=True)
def block_real_subprocess_calls(monkeypatch: pytest.MonkeyPatch):
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


@pytest.fixture(autouse=True)
def stub_ensure_vendored_dependencies(ucv: ModuleType, monkeypatch: pytest.MonkeyPatch):
    """main() now calls lib.dependencies.ensure_vendored_dependencies
    first, but every main()-level test here runs against a fake chart
    directory with no vendored sub-charts at all. Stubbed to a no-op by
    default; a test exercising the guard itself puts the real one back
    via its own monkeypatch.setattr, same as any other autouse default."""
    monkeypatch.setattr(ucv, "ensure_vendored_dependencies", lambda chart_dir: None)


@pytest.fixture(autouse=True)
def stub_run_fix_doc_consistency(ucv: ModuleType, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """main() ends with run_fix_doc_consistency, which runs the real
    fix-doc-consistency script on the real chart. Recorded instead:
    returns one "fix-doc" item per call."""
    calls: list[str] = []

    def record() -> None:
        calls.append("fix-doc")

    monkeypatch.setattr(ucv, "complete_docs_and_finish", record)
    return calls
