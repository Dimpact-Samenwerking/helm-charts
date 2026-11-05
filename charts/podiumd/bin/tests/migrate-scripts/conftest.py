"""Load the operator scripts in charts/podiumd/scripts/: migrate_common and the hyphenated migrate-*.py."""

import importlib.util
import sys

from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"
# The scripts import migrate_common from their own directory.
sys.path.insert(0, str(SCRIPTS_DIR))


def load_script(file_name: str) -> ModuleType:
    """The module of SCRIPTS_DIR/file_name, loaded once per session."""
    name = file_name.removesuffix(".py").replace("-", "_").replace(".", "_")
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, SCRIPTS_DIR / file_name)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # dataclasses look the module up in sys.modules while it loads.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def script() -> Callable[[str], ModuleType]:
    """load_script, for tests parametrized over script file names."""
    return load_script


@pytest.fixture(scope="session")
def common() -> ModuleType:
    return load_script("migrate_common.py")


@pytest.fixture(scope="session")
def zookeeper() -> ModuleType:
    return load_script("migrate-zookeeper-hooks-image-4.10.0.py")
