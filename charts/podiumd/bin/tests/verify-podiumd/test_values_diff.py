"""check_values_deltas_empty_sections and check_values_deltas_rowless_headings: values-deltas.md sections."""

from pathlib import Path
from types import ModuleType

import pytest

DEPS = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
TABLE = "## Component versions\n\n| Component | App version | Helm chart | Notes |\n| --- | --- | --- | --- |\n"
ZAC_ROW = "| zac | 5.0.2 → 5.1.0 | 1.0.297 | - |\n"
# Not checked against values.yaml, whether right or not.
KEY_LINE_SECTION = "# Values deltas\n\n## zac 5.0.2 → 5.1.0\n\n- Key `zac.notAKey` was added.\n"


def test_empty_section_is_flagged(libdocsconsistencyvaluesdiff: ModuleType, tmp_path: Path):
    doc = tmp_path / "values-deltas.md"
    doc.write_text("# Values deltas\n\n## zac 5.0.2 → 5.1.0\n\n", encoding="utf-8")
    assert libdocsconsistencyvaluesdiff.check_values_deltas_empty_sections(doc) == [
        'values-deltas.md: "## zac 5.0.2 → 5.1.0" section has nothing under its own heading'
    ]


def test_a_key_line_is_section_content(libdocsconsistencyvaluesdiff: ModuleType, tmp_path: Path):
    doc = tmp_path / "values-deltas.md"
    doc.write_text(KEY_LINE_SECTION, encoding="utf-8")
    assert libdocsconsistencyvaluesdiff.check_values_deltas_empty_sections(doc) == []


@pytest.mark.parametrize(("rows", "expected"), [(ZAC_ROW, 0), ("", 1)])
def test_rowless_heading(libdocsconsistencyvaluesdiff: ModuleType, tmp_path: Path, rows: str, expected: int):
    doc = tmp_path / "values-deltas.md"
    doc.write_text(KEY_LINE_SECTION, encoding="utf-8")
    upgrade = tmp_path / "upgrade.md"
    upgrade.write_text(TABLE + rows, encoding="utf-8")
    inputs = libdocsconsistencyvaluesdiff.ValuesDeltaInputs(DEPS)
    assert len(libdocsconsistencyvaluesdiff.check_values_deltas_rowless_headings(doc, upgrade, inputs)) == expected
