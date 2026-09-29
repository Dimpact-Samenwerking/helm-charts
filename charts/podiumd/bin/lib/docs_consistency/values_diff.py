"""Check a component's values.yaml schema changes are mentioned in its values-deltas.md section."""

import re

from dataclasses import dataclass
from pathlib import Path

from lib.chart.chart_yaml import ChartDependency
from lib.component_docs.values_delta_sections import find_values_delta_section
from lib.upgradedoc.grouped_comments_and_changes_block import diff_keys
from lib.upgradedoc.grouped_comments_and_changes_block import pair_renames
from lib.upgradedoc.sorting_and_ordering import parse_values_delta_sections
from lib.upgradedoc.version_cells_and_key_changes import strip_fenced_code_blocks
from lib.yaml_types import YamlMapping


@dataclass
class ValuesDeltaInputs:
    """Inputs for the schema diff: baseline_values, values, deps, canonical_names."""

    baseline_values: YamlMapping | None
    values: YamlMapping | None
    deps: list[ChartDependency]
    canonical_names: dict[str, tuple[str, ...]] | None = None


KeyPath = tuple[str, ...]
# (added, removed, renamed) for one component's values.yaml subtree.
KeyChanges = tuple[list[KeyPath], list[KeyPath], list[tuple[KeyPath, KeyPath]]]


def _diff_component_key(values_key: str, inputs: ValuesDeltaInputs) -> KeyChanges:
    """(added, removed, renamed) paths in one component's subtree vs baseline."""
    baseline_subtree = inputs.baseline_values.get(values_key, {}) if isinstance(inputs.baseline_values, dict) else {}
    current_subtree = inputs.values.get(values_key, {}) if isinstance(inputs.values, dict) else {}
    diffs: list[tuple[str, KeyPath]] = list(diff_keys(baseline_subtree, current_subtree, (values_key,)))
    added: list[KeyPath] = [p for kind, p in diffs if kind == "added"]
    removed: list[KeyPath] = [p for kind, p in diffs if kind == "removed"]
    renamed, added, removed = pair_renames(added, removed, baseline_subtree, current_subtree)
    return added, removed, renamed


def _added_removed_mentions(doc_path: Path, values_key: str, paths: list[KeyPath], backtick_spans: set[str], verb: str):
    """One issue per path in `paths` (added or removed keys, per `verb`)
    that isn't backtick-quoted anywhere in values_key's own section."""
    issues: list[str] = []
    for path in paths:
        dotted = ".".join(path)
        if dotted not in backtick_spans:
            issues.append(
                f'{doc_path.name}: key "{dotted}" was {verb} but is not mentioned '
                f'(backtick-quoted) in "{values_key}"\'s own section'
            )
    return issues


def _rename_mentions(doc_path: Path, values_key: str, renamed: list[tuple[KeyPath, KeyPath]], backtick_spans: set[str]):
    """One issue per (old, new) rename pair not backtick-quoted on BOTH
    sides within values_key's own section."""
    issues: list[str] = []
    for old_path, new_path in renamed:
        old_dotted, new_dotted = ".".join(old_path), ".".join(new_path)
        if not (old_dotted in backtick_spans and new_dotted in backtick_spans):
            issues.append(
                f'{doc_path.name}: key "{old_dotted}" appears renamed to "{new_dotted}" '
                f"but this rename is not mentioned (backtick-quoted, both sides) in "
                f'"{values_key}"\'s own section'
            )
    return issues


def _check_key_section_mentions(
    doc_path: Path, text: str, values_key: str, changes: KeyChanges, inputs: ValuesDeltaInputs
):
    """Issues when values_key has no "## ..." section or a change isn't backtick-quoted in it."""
    added, removed, renamed = changes
    section = find_values_delta_section(text, values_key, inputs.deps, inputs.canonical_names)
    if section is None:
        return [
            (
                f'{doc_path.name}: component "{values_key}" has a values.yaml schema change '
                f'vs upgrade_docs_baseline but has no "## ..." section of its own'
            )
        ]

    lines = text.splitlines(keepends=True)
    section_text = "".join(lines[section["start"] : section["end"]])
    backtick_spans = set(re.findall(r"`([^`]+)`", strip_fenced_code_blocks(section_text)))

    issues: list[str] = []
    issues.extend(_added_removed_mentions(doc_path, values_key, added, backtick_spans, "added"))
    issues.extend(_added_removed_mentions(doc_path, values_key, removed, backtick_spans, "removed"))
    issues.extend(_rename_mentions(doc_path, values_key, renamed, backtick_spans))
    return issues


def _check_empty_sections(doc_path: Path, text: str):
    """Flag every "## ..." section with an entirely blank body."""
    lines = text.splitlines(keepends=True)
    return [
        f'{doc_path.name}: "## {section["heading"]}" section has nothing under its own heading'
        for section in parse_values_delta_sections(text)
        if not "".join(lines[section["start"] + 1 : section["end"]]).strip()
    ]


def check_values_deltas_content(doc_path: Path, actual_changed_keys: set[str], inputs: ValuesDeltaInputs):
    """Check each component with a values.yaml schema change has its own section mentioning it.

    Each added/removed/renamed key must be backtick-quoted within that component's
    section; a mention elsewhere doesn't count. Pure version bumps need no section
    (the upgrade doc covers them); `actual_changed_keys` only scopes which subtrees are
    diffed. Empty sections are flagged too.
    """
    text = doc_path.read_text(encoding="utf-8")
    no_changes_claimed = bool(
        re.search(r"no\s+gemeente\s+`?podiumd\.yml`?\s+changes\s+are\s+required", text, re.IGNORECASE)
    )

    issues: list[str] = []
    for values_key in sorted(actual_changed_keys):
        changes = _diff_component_key(values_key, inputs)
        if not any(changes):
            continue
        issues.extend(_check_key_section_mentions(doc_path, text, values_key, changes, inputs))

    issues.extend(_check_empty_sections(doc_path, text))

    if issues and no_changes_claimed:
        issues.insert(
            0,
            f'{doc_path.name}: claims "No gemeente podiumd.yml changes are required" '
            f"but {len(issues)} key change(s) were found — see below",
        )
    return issues
