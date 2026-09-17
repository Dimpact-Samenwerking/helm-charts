"""Makes scripts/lib importable as a regular package for its own test suite,
the same way each script adds scripts/ to sys.path before `from lib.x import y`."""

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SCRIPTS_DIR))

import lib.baseline_report as baseline_report
import lib.chart as chart
import lib.component_docs as component_docs
import lib.confluence_tables as confluence_tables
import lib.dependencies as dependencies
import lib.docs_consistency as docs_consistency
import lib.gitutil as gitutil
import lib.image_docs as image_docs
import lib.image_version as image_version
import lib.procutil as procutil
import lib.registry as registry
import lib.release_baseline as release_baseline
import lib.repo_access as repo_access
import lib.repo_access_cache as repo_access_cache
import lib.upgradedoc_app_version_and_image_paths as upgradedoc_app_version_and_image_paths
import lib.upgradedoc_consistency_checks as upgradedoc_consistency_checks
import lib.upgradedoc_grouped_comments_and_changes_block as upgradedoc_grouped_comments_and_changes_block
import lib.upgradedoc_images_manifest_list_diff as upgradedoc_images_manifest_list_diff
import lib.upgradedoc_images_manifest_ordering as upgradedoc_images_manifest_ordering
import lib.upgradedoc_resolve_component_row as upgradedoc_resolve_component_row
import lib.upgradedoc_sorting_and_ordering as upgradedoc_sorting_and_ordering
import lib.upgradedoc_string_and_parsing_basics as upgradedoc_string_and_parsing_basics
import lib.upgradedoc_version_cells_and_key_changes as upgradedoc_version_cells_and_key_changes


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
def libbaselinereport():
    return baseline_report


@pytest.fixture(scope="session")
def libdependencies():
    return dependencies


@pytest.fixture(scope="session")
def librepoaccess():
    return repo_access


@pytest.fixture(scope="session")
def librepoaccesscache():
    return repo_access_cache


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
def librelease_baseline():
    return release_baseline


@pytest.fixture(scope="session")
def libupgradedocbasics():
    return upgradedoc_string_and_parsing_basics


@pytest.fixture(scope="session")
def libupgradedocsorting():
    return upgradedoc_sorting_and_ordering


@pytest.fixture(scope="session")
def libupgradedocconsistency():
    return upgradedoc_consistency_checks


@pytest.fixture(scope="session")
def libupgradedocresolverow():
    return upgradedoc_resolve_component_row


@pytest.fixture(scope="session")
def libupgradedocversioncells():
    return upgradedoc_version_cells_and_key_changes


@pytest.fixture(scope="session")
def libupgradedocappversion():
    return upgradedoc_app_version_and_image_paths


@pytest.fixture(scope="session")
def libupgradedocmanifestordering():
    return upgradedoc_images_manifest_ordering


@pytest.fixture(scope="session")
def libupgradedocmanifestdiff():
    return upgradedoc_images_manifest_list_diff


@pytest.fixture(scope="session")
def libupgradedoccomments():
    return upgradedoc_grouped_comments_and_changes_block


@pytest.fixture(scope="session")
def libimagedocs():
    return image_docs


@pytest.fixture(scope="session")
def libcomponentdocs():
    return component_docs


@pytest.fixture(scope="session")
def libdocsconsistency():
    return docs_consistency
