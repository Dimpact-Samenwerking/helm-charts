"""Makes scripts/lib importable as a regular package for its own test suite,
the same way each script adds scripts/ to sys.path before `from lib.x import y`."""
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SCRIPTS_DIR))

import lib.chart as chart
import lib.gitutil as gitutil
import lib.procutil as procutil
import lib.registry as registry
import lib.upgradedoc as upgradedoc


@pytest.fixture(scope="session")
def libprocutil():
    return procutil


@pytest.fixture(scope="session")
def libregistry():
    return registry


@pytest.fixture(scope="session")
def libchart():
    return chart


@pytest.fixture(scope="session")
def libgitutil():
    return gitutil


@pytest.fixture(scope="session")
def libupgradedoc():
    return upgradedoc
