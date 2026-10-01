"""Check a component's values.yaml schema changes are listed in its values-deltas.md section."""

import re

from dataclasses import dataclass
from pathlib import Path

from lib.chart.chart_yaml import ChartDependency
from lib.component_docs.values_delta_sections import has_blank_body
from lib.component_docs.values_delta_sections import section_block_text
from lib.component_docs.values_delta_sections import values_delta_section_for
from lib.upgradedoc.sorting_and_ordering import parse_values_delta_sections
from lib.upgradedoc.version_cells_and_key_changes import key_change_lines
from lib.upgradedoc.version_cells_and_key_changes import missing_key_change_lines
from lib.yaml_types import YamlMapping


@dataclass
class ValuesDeltaInputs:
    """Inputs for the schema diff: baseline_values, values, deps, canonical_names."""

    baseline_values: YamlMapping | None
    values: YamlMapping | None
    deps: list[ChartDependency]
    canonical_names: dict[str, tuple[str, ...]] | None = None


def _check_key_section_lines(
    doc_path: Path, text: str, values_key: str, key_lines: list[str], inputs: ValuesDeltaInputs
):
    """Issues when values_key has no "## ..." section or the section lacks one of its generated key lines."""
    section = values_delta_section_for(text, values_key, inputs.deps, inputs.canonical_names)
    if section is None:
        return [
            (
                f'{doc_path.name}: component "{values_key}" has a values.yaml schema change '
                f'vs upgrade_docs_baseline but has no "## ..." section of its own'
            )
        ]
    return [
        f'{doc_path.name}: "{values_key}"\'s own section lacks the generated line "{line.strip()}"'
        for line in missing_key_change_lines(section_block_text(text, section), key_lines)
    ]


def _check_empty_sections(doc_path: Path, text: str):
    """Flag every "## ..." section with an entirely blank body."""
    lines = text.splitlines(keepends=True)
    return [
        f'{doc_path.name}: "## {section["heading"]}" section has nothing under its own heading'
        for section in parse_values_delta_sections(text)
        if has_blank_body(lines, section)
    ]


def check_values_deltas_content(doc_path: Path, actual_changed_keys: set[str], inputs: ValuesDeltaInputs):
    """Check each component with a values.yaml schema change has its own section mentioning it.

    Each added/removed/renamed key needs its generated describe_key_changes line
    in that component's section; a prose mention doesn't count. Pure version bumps need no section
    (the upgrade doc covers them); `actual_changed_keys` only scopes which subtrees are
    diffed. Empty sections are flagged too.
    """
    text = doc_path.read_text(encoding="utf-8")
    no_changes_claimed = bool(
        re.search(r"no\s+gemeente\s+`?podiumd\.yml`?\s+changes\s+are\s+required", text, re.IGNORECASE)
    )

    issues: list[str] = []
    for values_key in sorted(actual_changed_keys):
        key_lines = key_change_lines(values_key, inputs.baseline_values, inputs.values)
        if key_lines:
            issues.extend(_check_key_section_lines(doc_path, text, values_key, key_lines, inputs))

    issues.extend(_check_empty_sections(doc_path, text))

    if issues and no_changes_claimed:
        issues.insert(
            0,
            f'{doc_path.name}: claims "No gemeente podiumd.yml changes are required" '
            f"but {len(issues)} key change(s) were found — see below",
        )
    return issues
