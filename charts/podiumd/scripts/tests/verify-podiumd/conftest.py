"""Loads verify-podiumd.py (a hyphenated filename, not importable normally)
as a module named `vp` so tests can call its functions directly."""
import importlib.util
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "verify-podiumd.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("verify_podiumd", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def vp():
    return _load_module()


def make_dep(name, version, alias=None, repository="@example", condition=None):
    dep = {"name": name, "version": version, "repository": repository}
    if alias:
        dep["alias"] = alias
    if condition:
        dep["condition"] = condition
    return dep
