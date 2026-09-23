"""Loads render-podiumd (a hyphenated filename, not importable normally)
as a module named `rp`."""

import importlib.util
import sys

from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SCRIPTS_DIR))

SCRIPT_PATH = SCRIPTS_DIR / "render-podiumd"

import lib.render_scope as render_scope


def _load_module():
    loader = SourceFileLoader("render_podiumd", str(SCRIPT_PATH))
    spec = importlib.util.spec_from_file_location("render_podiumd", SCRIPT_PATH, loader=loader)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def rp():
    return _load_module()


@pytest.fixture(scope="session")
def librenderscope():
    return render_scope


@pytest.fixture(autouse=True)
def stub_require_vendored_dependencies(rp, monkeypatch):
    """main() now calls lib.dependencies.require_vendored_dependencies
    first, but every main()-level test here runs against a fake chart
    directory with no vendored sub-charts at all. Stubbed to a no-op by
    default; a test exercising the guard itself puts the real one back
    via its own monkeypatch.setattr, same as any other autouse default."""
    monkeypatch.setattr(rp, "require_vendored_dependencies", lambda chart_dir: None)
