"""Loads verify-release-table-with-podiumd (a hyphenated filename, not
importable normally) as a module named `vrt` so tests can call its
functions directly."""

import importlib.util

from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "verify-release-table-with-podiumd"


@pytest.fixture(scope="session")
def vrt():
    loader = SourceFileLoader("verify_release_table_with_podiumd", str(SCRIPT_PATH))
    spec = importlib.util.spec_from_file_location("verify_release_table_with_podiumd", SCRIPT_PATH, loader=loader)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def stub_require_vendored_dependencies(vrt, monkeypatch):
    """main() now calls lib.dependencies.require_vendored_dependencies
    first, but every main()-level test here runs against a fake chart
    directory with no vendored sub-charts at all. Stubbed to a no-op by
    default; a test exercising the guard itself puts the real one back
    via its own monkeypatch.setattr, same as any other autouse default."""
    monkeypatch.setattr(vrt, "require_vendored_dependencies", lambda chart_dir: None)
