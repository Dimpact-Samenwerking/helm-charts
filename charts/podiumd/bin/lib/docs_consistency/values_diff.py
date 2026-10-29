"""Check the values-deltas.md "## ..." sections: none empty, and every generated heading names an upgrade-doc row."""

from dataclasses import dataclass
from pathlib import Path

from lib.chart.chart_yaml import ChartDependency
from lib.component_docs.owned_parts import generated_heading_name
from lib.component_docs.values_delta_sections import has_blank_body
from lib.upgradedoc.consistency_checks import find_changes_row_correspondence_gaps
from lib.upgradedoc.sorting_and_ordering import parse_values_delta_sections
from lib.upgradedoc.string_and_parsing_basics import parse_upgrade_doc_rows


@dataclass
class ValuesDeltaInputs:
    """Inputs for matching headings to upgrade-doc rows: deps, canonical_names."""

    deps: list[ChartDependency]
    canonical_names: dict[str, tuple[str, ...]] | None = None


def check_values_deltas_empty_sections(doc_path: Path):
    """Flag every "## ..." section with an entirely blank body."""
    text = doc_path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    return [
        f'{doc_path.name}: "## {section["heading"]}" section has nothing under its own heading'
        for section in parse_values_delta_sections(text)
        if has_blank_body(lines, section)
    ]


def check_values_deltas_rowless_headings(
    doc_path: Path, upgrade_doc_path: Path, inputs: ValuesDeltaInputs
) -> list[str]:
    """Flag a generated "## <component> <old> → <new>" heading naming no row of the upgrade doc's table.

    Such a heading names a version change that isn't there (the component is
    back at its baseline, or removed). A hand-written heading (anything beyond
    the generated shape) is the user's and is left alone.
    """
    if not upgrade_doc_path.is_file():
        return []
    headings = [
        section["heading"]
        for section in parse_values_delta_sections(doc_path.read_text(encoding="utf-8"))
        if generated_heading_name(section["heading"]) is not None
    ]
    _rows_without_heading, rowless = find_changes_row_correspondence_gaps(
        parse_upgrade_doc_rows(upgrade_doc_path.read_text(encoding="utf-8")),
        headings,
        inputs.deps,
        inputs.canonical_names or {},
    )
    return [
        f'{doc_path.name}: "## {heading}" names no row of the "Component versions" table in '
        f"{upgrade_doc_path.name}; update or remove the heading by hand"
        for heading in rowless
    ]
