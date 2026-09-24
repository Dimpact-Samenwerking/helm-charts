"""lib.docs_consistency — match_changes_item_to_entry: matches a plain
(non-component) "# Changes:" item to its images-manifest entry by
basename, used when match_dependency_excluding_sidecar_names already
ruled out a real Chart.yaml dependency — and the "Component versions"
row's source-cell check."""

from pathlib import Path
from types import ModuleType

import pytest

from lib.docs_consistency.check_context import ComponentRowsResult
from lib.docs_consistency.check_context import RowContext

# --- match_changes_item_to_entry ---


def test_match_changes_item_to_entry_canonical_sidecar_name_matches_own_basename(libimagesmanifest: ModuleType):
    """A canonical "<key> - <basename>" sidecar name (see
    lib.chart.canonical_sidecar_row_names) is matched on its OWN
    basename only, not the whole string — real collision: "keycloak-
    operator - postgres" (the postgres image bundled with the keycloak-
    operator dependency) must match the "postgres" entry, not the
    unrelated "keycloak" entry its leading word happens to fuzzy-match
    equally well on a same-length word."""
    keycloak_entry = {"name": "keycloak/keycloak", "version": "26.7.2"}
    postgres_entry = {"name": "postgres", "version": "16.15"}

    match = libimagesmanifest.match_changes_item_to_entry(
        "keycloak-operator - postgres", [keycloak_entry, postgres_entry]
    )

    assert match is postgres_entry


def test_match_changes_item_to_entry_plain_name_matches_by_basename(libimagesmanifest: ModuleType):
    """No " - " delimiter: falls back to matching the whole item name
    against entry basenames, unchanged from before the fix above."""
    entry = {"name": "library/python", "version": "3.14.7-slim"}

    match = libimagesmanifest.match_changes_item_to_entry("python", [entry])

    assert match is entry


def test_match_changes_item_to_entry_no_match_returns_none(libimagesmanifest: ModuleType):
    entries = [{"name": "postgres", "version": "16.15"}]

    match = libimagesmanifest.match_changes_item_to_entry("gotenberg", entries)

    assert match is None


# --- _check_row_baseline_versions ---


def _source_app_mismatches(libdocsconsistency: ModuleType, app_source: str, baseline_app: str | None):
    """Mismatches for one "mi" row (target app 2.0.0, its App cell's
    source version app_source) whose Chart.yaml dependency line existed
    at podiumd-4.8.5 (baseline_resolved True), with baseline_app as its
    app version there."""
    row = {"name": "mi", "app_source": app_source, "app": "2.0.0", "chart_source": "1.0.0", "chart": "1.0.0"}
    resolved = {
        "kind": "dependency",
        "dep": {"name": "mi", "version": "1.0.0"},
        "sidecar_path": None,
        "values_key": "mi",
        "top_level_key": "mi",
        "target_chart": "1.0.0",
        "target_app": "2.0.0",
        "baseline_resolved": True,
        "baseline_chart": "1.0.0",
        "baseline_app": baseline_app,
    }
    row_ctx = RowContext(Path("4.8.5-to-4.9.0-upgrade.md"), "podiumd-4.8.5")
    result = ComponentRowsResult([], set(), {}, {}, set())
    libdocsconsistency._check_row_baseline_versions(row, row_ctx, resolved, "mi", result)
    return result.mismatches


def test_check_row_baseline_versions_flags_stale_transition_for_new_app_version(libdocsconsistency: ModuleType):
    """baseline_resolved True but no baseline app version: fix-doc-
    consistency rewrites the cell to "2.0.0 (new)", so a stale "1.9.0 →
    2.0.0" cell must be flagged, not skipped."""
    mismatches = _source_app_mismatches(libdocsconsistency, "1.9.0", None)
    assert mismatches == [
        'mi ("mi") source app: podiumd-4.8.5 has no app version (new), 4.8.5-to-4.9.0-upgrade.md says "1.9.0"'
    ]


# "2.0.0 (new)" and "1.9.0 → 2.0.0" cells, as parse_upgrade_doc_rows reads them.
@pytest.mark.parametrize(("app_source", "baseline_app"), [("2.0.0", None), ("1.9.0", "1.9.0")])
def test_check_row_baseline_versions_accepts_the_cell_fix_doc_consistency_writes(
    libdocsconsistency: ModuleType, app_source: str, baseline_app: str | None
):
    assert not _source_app_mismatches(libdocsconsistency, app_source, baseline_app)
