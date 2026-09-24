"""Makes scripts/lib importable as a regular package for its own test suite,
the same way each script adds scripts/ to sys.path before `from lib.x import y`."""

import sys

from pathlib import Path
from types import ModuleType

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SCRIPTS_DIR))

import lib.baseline_report as baseline_report
import lib.chart.historical_baselines as chart_historical_baselines
import lib.chart.nested_subchart_identity as chart_nested_subchart_identity
import lib.chart.pull_and_subchart_resolution as chart_pull_and_subchart_resolution
import lib.chart.registered_paths as chart_registered_paths
import lib.chart.release_baseline_basics as chart_release_baseline_basics
import lib.chart.repo_and_path_resolution as chart_repo_and_path_resolution
import lib.chart.values_tree_primitives as chart_values_tree_primitives
import lib.chart_lock as chart_lock
import lib.component_docs as component_docs
import lib.component_docs.baseline_doc_stubs as component_docs_baseline_doc_stubs
import lib.component_docs.changes_section as component_docs_changes_section
import lib.component_docs.images_manifest_changes_header as component_docs_images_manifest_changes_header
import lib.component_docs.images_manifest_entries as component_docs_images_manifest_entries
import lib.component_docs.values_delta_sections as component_docs_values_delta_sections
import lib.confluence_tables as confluence_tables
import lib.dependencies as dependencies
import lib.docs_consistency.images_manifest_format as docs_consistency_images_manifest_format
import lib.gitutil as gitutil
import lib.image.docs as image_docs
import lib.image.version as image_version
import lib.procutil as procutil
import lib.registry as registry
import lib.release_baseline as release_baseline
import lib.repo_access as repo_access
import lib.repo_access_cache as repo_access_cache
import lib.upgradedoc.app_version_and_image_paths as upgradedoc_app_version_and_image_paths
import lib.upgradedoc.consistency_checks as upgradedoc_consistency_checks
import lib.upgradedoc.grouped_comments_and_changes_block as upgradedoc_grouped_comments_and_changes_block
import lib.upgradedoc.images_manifest_list_diff as upgradedoc_images_manifest_list_diff
import lib.upgradedoc.images_manifest_ordering as upgradedoc_images_manifest_ordering
import lib.upgradedoc.resolve_component_row as upgradedoc_resolve_component_row
import lib.upgradedoc.sorting_and_ordering as upgradedoc_sorting_and_ordering
import lib.upgradedoc.string_and_parsing_basics as upgradedoc_string_and_parsing_basics
import lib.upgradedoc.version_cells_and_key_changes as upgradedoc_version_cells_and_key_changes


@pytest.fixture(scope="session")
def libprocutil() -> ModuleType:
    return procutil


@pytest.fixture(scope="session")
def libregistry() -> ModuleType:
    return registry


@pytest.fixture(scope="session")
def libchartvaluestreeprimitives() -> ModuleType:
    return chart_values_tree_primitives


@pytest.fixture(scope="session")
def libchartregisteredpaths() -> ModuleType:
    return chart_registered_paths


@pytest.fixture(scope="session")
def libchartnestedsubchartidentity() -> ModuleType:
    return chart_nested_subchart_identity


@pytest.fixture(scope="session")
def libchartreleasebaselinebasics() -> ModuleType:
    return chart_release_baseline_basics


@pytest.fixture(scope="session")
def libchartpullandsubchartresolution() -> ModuleType:
    return chart_pull_and_subchart_resolution


@pytest.fixture(scope="session")
def libchartrepoandpathresolution() -> ModuleType:
    return chart_repo_and_path_resolution


@pytest.fixture(scope="session")
def libcharthistoricalbaselines() -> ModuleType:
    return chart_historical_baselines


@pytest.fixture(scope="session")
def libbaselinereport() -> ModuleType:
    return baseline_report


@pytest.fixture(scope="session")
def libdependencies() -> ModuleType:
    return dependencies


@pytest.fixture(scope="session")
def libchartlock() -> ModuleType:
    return chart_lock


@pytest.fixture(scope="session")
def librepoaccess() -> ModuleType:
    return repo_access


@pytest.fixture(scope="session")
def librepoaccesscache() -> ModuleType:
    return repo_access_cache


@pytest.fixture(scope="session")
def libimageversion() -> ModuleType:
    return image_version


@pytest.fixture(scope="session")
def libconfluencetables() -> ModuleType:
    return confluence_tables


@pytest.fixture(scope="session")
def libgitutil() -> ModuleType:
    return gitutil


@pytest.fixture(scope="session")
def librelease_baseline() -> ModuleType:
    return release_baseline


@pytest.fixture(scope="session")
def libupgradedocbasics() -> ModuleType:
    return upgradedoc_string_and_parsing_basics


@pytest.fixture(scope="session")
def libupgradedocsorting() -> ModuleType:
    return upgradedoc_sorting_and_ordering


@pytest.fixture(scope="session")
def libupgradedocconsistency() -> ModuleType:
    return upgradedoc_consistency_checks


@pytest.fixture(scope="session")
def libupgradedocresolverow() -> ModuleType:
    return upgradedoc_resolve_component_row


@pytest.fixture(scope="session")
def libupgradedocversioncells() -> ModuleType:
    return upgradedoc_version_cells_and_key_changes


@pytest.fixture(scope="session")
def libupgradedocappversion() -> ModuleType:
    return upgradedoc_app_version_and_image_paths


@pytest.fixture(scope="session")
def libupgradedocmanifestordering() -> ModuleType:
    return upgradedoc_images_manifest_ordering


@pytest.fixture(scope="session")
def libupgradedocmanifestdiff() -> ModuleType:
    return upgradedoc_images_manifest_list_diff


@pytest.fixture(scope="session")
def libupgradedoccomments() -> ModuleType:
    return upgradedoc_grouped_comments_and_changes_block


@pytest.fixture(scope="session")
def libimagedocs() -> ModuleType:
    return image_docs


@pytest.fixture(scope="session")
def libcomponentdocs() -> ModuleType:
    return component_docs


@pytest.fixture(scope="session")
def libcomponentdocsbaselinedocstubs() -> ModuleType:
    return component_docs_baseline_doc_stubs


@pytest.fixture(scope="session")
def libcomponentdocsheader() -> ModuleType:
    return component_docs_images_manifest_changes_header


@pytest.fixture(scope="session")
def libcomponentdocschanges() -> ModuleType:
    return component_docs_changes_section


@pytest.fixture(scope="session")
def libcomponentdocsdeltas() -> ModuleType:
    return component_docs_values_delta_sections


@pytest.fixture(scope="session")
def libcomponentdocsentries() -> ModuleType:
    return component_docs_images_manifest_entries


@pytest.fixture(scope="session")
def libimagesmanifest() -> ModuleType:
    return docs_consistency_images_manifest_format
