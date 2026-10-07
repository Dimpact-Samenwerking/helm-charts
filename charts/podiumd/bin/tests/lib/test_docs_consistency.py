"""lib.docs_consistency: the "Component versions" source-cell check and the upgrade doc header checks."""

from pathlib import Path
from types import ModuleType
from types import SimpleNamespace

import pytest

from lib.docs_consistency.check_context import ComponentRowsResult
from lib.docs_consistency.check_context import DocQuery
from lib.docs_consistency.check_context import RowContext

# --- _check_row_baseline_versions ---


def _source_app_mismatches(libdocsconsistency: ModuleType, app_source: str | None, baseline_app: str | None):
    """Mismatches for one "mi" row (target app 2.0.0, cell source app_source) with baseline_app at 4.8.5."""
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
    result = ComponentRowsResult([], {}, {})
    libdocsconsistency._check_row_baseline_versions(row, row_ctx, resolved, "mi", result)
    return result.mismatches


def test_check_row_baseline_versions_flags_stale_transition_for_new_app_version(libdocsconsistency: ModuleType):
    """A known baseline without app version is rewritten to "2.0.0 (new)", so "1.9.0 → 2.0.0" is flagged."""
    mismatches = _source_app_mismatches(libdocsconsistency, "1.9.0", None)
    assert mismatches == [
        'mi ("mi") source app: podiumd-4.8.5 has no app version (new), 4.8.5-to-4.9.0-upgrade.md says "1.9.0"'
    ]


# "2.0.0 (new)" and "1.9.0 → 2.0.0" cells, as parse_upgrade_doc_rows reads them.
@pytest.mark.parametrize(("app_source", "baseline_app"), [(None, None), ("1.9.0", "1.9.0")])
def test_check_row_baseline_versions_accepts_the_cell_fix_doc_consistency_writes(
    libdocsconsistency: ModuleType, app_source: str | None, baseline_app: str | None
):
    assert not _source_app_mismatches(libdocsconsistency, app_source, baseline_app)


# --- _doc_header_mismatches ---


def test_doc_header_flags_a_stale_intro_baseline(libdocsconsistency: ModuleType, tmp_path: Path):
    doc = tmp_path / "4.9.3-to-4.10.0-upgrade.md"
    doc.write_text(
        "# Upgrade guide: PodiumD 4.9.3 → 4.10.0\n\nThis is the upgrade guide for environments already on **4.9.1**.\n",
        encoding="utf-8",
    )
    ctx = SimpleNamespace(doc_query=DocQuery(tmp_path, "4.10.0", "4.9.3", is_bare_version=True))
    assert libdocsconsistency._doc_header_mismatches(doc, ctx) == [
        "4.9.3-to-4.10.0-upgrade.md intro names baseline **4.9.1**, not **4.9.3**"
    ]
