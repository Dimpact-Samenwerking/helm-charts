"""Checks that a component's values.yaml schema changes are properly
mentioned in its own values-deltas.md section — used by
lib.docs_consistency.check_docs_consistency."""

import re

from dataclasses import dataclass

from lib.component_docs.values_delta_sections import find_values_delta_section
from lib.upgradedoc.grouped_comments_and_changes_block import diff_keys
from lib.upgradedoc.grouped_comments_and_changes_block import pair_renames
from lib.upgradedoc.sorting_and_ordering import parse_values_delta_sections
from lib.upgradedoc.version_cells_and_key_changes import strip_fenced_code_blocks


@dataclass
class ValuesDeltaInputs:
    """baseline_values/values/deps/canonical_names bundled since every
    step of the schema diff below (subtree lookup, rename pairing,
    section lookup) needs the same four things together."""

    baseline_values: dict
    values: dict
    deps: list
    canonical_names: object = None


def _diff_component_key(values_key, inputs):
    """(added, removed, renamed) path lists for one component's
    values.yaml subtree vs baseline — all empty when unchanged."""
    baseline_subtree = inputs.baseline_values.get(values_key, {}) if isinstance(inputs.baseline_values, dict) else {}
    current_subtree = inputs.values.get(values_key, {}) if isinstance(inputs.values, dict) else {}
    diffs = list(diff_keys(baseline_subtree, current_subtree, (values_key,)))
    added = [p for kind, p in diffs if kind == "added"]
    removed = [p for kind, p in diffs if kind == "removed"]
    renamed, added, removed = pair_renames(added, removed, baseline_subtree, current_subtree)
    return added, removed, renamed


def _added_removed_mentions(doc_path, values_key, paths, backtick_spans, verb):
    """One issue per path in `paths` (added or removed keys, per `verb`)
    that isn't backtick-quoted anywhere in values_key's own section."""
    issues = []
    for path in paths:
        dotted = ".".join(path)
        if dotted not in backtick_spans:
            issues.append(
                f'{doc_path.name}: key "{dotted}" was {verb} but is not mentioned '
                f'(backtick-quoted) in "{values_key}"\'s own section'
            )
    return issues


def _rename_mentions(doc_path, values_key, renamed, backtick_spans):
    """One issue per (old, new) rename pair not backtick-quoted on BOTH
    sides within values_key's own section."""
    issues = []
    for old_path, new_path in renamed:
        old_dotted, new_dotted = ".".join(old_path), ".".join(new_path)
        if not (old_dotted in backtick_spans and new_dotted in backtick_spans):
            issues.append(
                f'{doc_path.name}: key "{old_dotted}" appears renamed to "{new_dotted}" '
                f"but this rename is not mentioned (backtick-quoted, both sides) in "
                f'"{values_key}"\'s own section'
            )
    return issues


def _check_key_section_mentions(doc_path, text, values_key, changes, inputs):
    """Verifies values_key has its own "## ..." section and that every
    change in it (added, removed, renamed) is backtick-quoted within
    that section — see check_values_deltas_content's own docstring."""
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

    issues = []
    issues.extend(_added_removed_mentions(doc_path, values_key, added, backtick_spans, "added"))
    issues.extend(_added_removed_mentions(doc_path, values_key, removed, backtick_spans, "removed"))
    issues.extend(_rename_mentions(doc_path, values_key, renamed, backtick_spans))
    return issues


def _check_empty_sections(doc_path, text):
    """Flags any "## ..." section whose own body is entirely blank — a
    heading with nothing under it, left over from before this rule
    existed (see lib.component_docs.prune_empty_values_delta_sections,
    fix-doc-consistency's own cleanup for exactly this)."""
    lines = text.splitlines(keepends=True)
    return [
        f'{doc_path.name}: "## {section["heading"]}" section has nothing under its own heading'
        for section in parse_values_delta_sections(text)
        if not "".join(lines[section["start"] + 1 : section["end"]]).strip()
    ]


def check_values_deltas_content(doc_path, actual_changed_keys, inputs):
    """For every top-level component key whose values.yaml SCHEMA
    changed vs upgrade_docs_baseline (a key was added/removed/renamed
    under it — see lib.upgradedoc.diff_keys/pair_renames), verify it has
    its own values-deltas.md section (see lib.upgradedoc.parse_values_
    delta_sections/changes_heading_identities/lib.component_docs.
    find_values_delta_section) and that every such change is actually
    mentioned (backtick-quoted, matching the doc convention)
    specifically WITHIN that section. A key mentioned only in some
    OTHER component's section (or nowhere at all) is exactly the drift
    this per-component-section convention exists to catch.

    A component that only bumped its app/chart version, with NO schema
    change, needs no section here at all — that transition is already
    covered by -upgrade.md's own table + Changes section, and values-
    deltas.md exists to tell gemeentes what THEIR OWN podiumd.yml needs
    to react to (see sync_values_delta_sections's own docstring for the
    same reasoning) — so `actual_changed_keys` (compute_changed_
    components' broader "changed in ANY way" set) is used only to scope
    WHICH keys' own subtrees get diffed, never to require a section on
    its own.

    `inputs` is a ValuesDeltaInputs bundling baseline_values/values/
    deps/canonical_names — see its own docstring.

    Also flags any "## ..." section whose own body is entirely
    blank — see _check_empty_sections."""
    text = doc_path.read_text(encoding="utf-8")
    no_changes_claimed = bool(
        re.search(r"no\s+gemeente\s+`?podiumd\.yml`?\s+changes\s+are\s+required", text, re.IGNORECASE)
    )

    issues = []
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
