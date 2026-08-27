"""Makes scripts/lib importable as a regular package for its own test suite,
the same way each script adds scripts/ to sys.path before `from lib.x import y`."""
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SCRIPTS_DIR))

import lib.chart as chart
import lib.confluence_tables as confluence_tables
import lib.dependencies as dependencies
import lib.gitutil as gitutil
import lib.image_docs as image_docs
import lib.image_version as image_version
import lib.procutil as procutil
import lib.registry as registry
import lib.repo_access as repo_access
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
def libdependencies():
    return dependencies


@pytest.fixture(scope="session")
def librepoaccess():
    return repo_access


@pytest.fixture(scope="session")
def libimageversion():
    return image_version


@pytest.fixture(scope="session")
def libconfluencetables():
    return confluence_tables


@pytest.fixture(scope="session")
def libgitutil():
    return gitutil


@pytest.fixture(scope="session")
def libupgradedoc():
    return upgradedoc


@pytest.fixture(scope="session")
def libimagedocs():
    return image_docs
