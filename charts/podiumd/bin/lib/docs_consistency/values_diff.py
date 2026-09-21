"""Checks that a component's values.yaml schema changes are properly
mentioned in its own values-deltas.md section — used by
lib.docs_consistency.check_docs_consistency."""

import re

from lib.component_docs.values_delta_sections import find_values_delta_section
from lib.upgradedoc_grouped_comments_and_changes_block import diff_keys, pair_renames
from lib.upgradedoc_sorting_and_ordering import parse_values_delta_sections
from lib.upgradedoc_version_cells_and_key_changes import strip_fenced_code_blocks


def check_values_deltas_content(doc_path, actual_changed_keys, baseline_values, values, deps, canonical_names=None):
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

    Also flags any "## ..." section whose own body is entirely
    blank — a heading with nothing under it, left over from before this
    rule existed (see lib.component_docs.prune_empty_values_delta_
    sections, fix-doc-consistency's own cleanup for exactly this)."""
    text = doc_path.read_text(encoding="utf-8")
    no_changes_claimed = bool(
        re.search(r"no\s+gemeente\s+`?podiumd\.yml`?\s+changes\s+are\s+required", text, re.IGNORECASE)
    )

    issues = []
    for values_key in sorted(actual_changed_keys):
        baseline_subtree = baseline_values.get(values_key, {}) if isinstance(baseline_values, dict) else {}
        current_subtree = values.get(values_key, {}) if isinstance(values, dict) else {}
        diffs = list(diff_keys(baseline_subtree, current_subtree, (values_key,)))
        added = [p for kind, p in diffs if kind == "added"]
        removed = [p for kind, p in diffs if kind == "removed"]
        renamed, added, removed = pair_renames(added, removed, baseline_subtree, current_subtree)
        if not (added or removed or renamed):
            continue

        section = find_values_delta_section(text, values_key, deps, canonical_names)
        if section is None:
            issues.append(
                f'{doc_path.name}: component "{values_key}" has a values.yaml schema change '
                f'vs upgrade_docs_baseline but has no "## ..." section of its own'
            )
            continue

        lines = text.splitlines(keepends=True)
        section_text = "".join(lines[section["start"] : section["end"]])
        backtick_spans = set(re.findall(r"`([^`]+)`", strip_fenced_code_blocks(section_text)))

        # mentioned() is called only below, within this same iteration,
        # before backtick_spans is rebound on the next values_key.
        def mentioned(span):
            return span in backtick_spans  # noqa: B023

        for path in added:
            dotted = ".".join(path)
            if not mentioned(dotted):
                issues.append(
                    f'{doc_path.name}: key "{dotted}" was added but is not mentioned '
                    f'(backtick-quoted) in "{values_key}"\'s own section'
                )
        for path in removed:
            dotted = ".".join(path)
            if not mentioned(dotted):
                issues.append(
                    f'{doc_path.name}: key "{dotted}" was removed but is not mentioned '
                    f'(backtick-quoted) in "{values_key}"\'s own section'
                )
        for old_path, new_path in renamed:
            old_dotted, new_dotted = ".".join(old_path), ".".join(new_path)
            if not (mentioned(old_dotted) and mentioned(new_dotted)):
                issues.append(
                    f'{doc_path.name}: key "{old_dotted}" appears renamed to "{new_dotted}" '
                    f"but this rename is not mentioned (backtick-quoted, both sides) in "
                    f'"{values_key}"\'s own section'
                )

    lines = text.splitlines(keepends=True)
    for section in parse_values_delta_sections(text):
        if not "".join(lines[section["start"] + 1 : section["end"]]).strip():
            issues.append(f'{doc_path.name}: "## {section["heading"]}" section has nothing under its own heading')

    if issues and no_changes_claimed:
        issues.insert(
            0,
            f'{doc_path.name}: claims "No gemeente podiumd.yml changes are required" '
            f"but {len(issues)} key change(s) were found — see below",
        )
    return issues
