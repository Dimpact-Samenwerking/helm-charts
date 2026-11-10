"""fix-doc-consistency's repairs of an upgrade guide and its values-deltas doc."""

from pathlib import Path

from lib.chart.values_tree_primitives import ValuesPath
from lib.chart.yaml_alias_groups import alias_groups
from lib.cli import print_section
from lib.cli import print_section_items
from lib.component_docs.aliased_pin_bullets import add_missing_pin_bullets
from lib.component_docs.changes_section import DocContext
from lib.component_docs.changes_section import add_missing_component_rows
from lib.component_docs.changes_section import fix_pointer_issues
from lib.component_docs.removed_item_docs import sync_removed_items
from lib.component_docs.values_delta_sections import prune_empty_values_delta_sections
from lib.fix_doc_consistency.component_version_table import fix_changes_heading_app_versions
from lib.fix_doc_consistency.component_version_table import fix_component_version_table
from lib.fix_doc_consistency.component_version_table import fix_values_delta_heading_app_versions
from lib.fix_doc_consistency.component_version_table import remove_unchanged_component_rows
from lib.fix_doc_consistency.rebase_state import RebaseState
from lib.fix_doc_consistency.text_helpers_and_repo_rename import collapse_multiple_blank_lines
from lib.fix_doc_consistency.text_helpers_and_repo_rename import retarget_heading_links
from lib.image.docs import add_missing_changes_sections
from lib.image.docs import add_missing_sidecar_rows
from lib.image.docs import rebuild_changes_sections_contradicting_rows
from lib.image.docs import update_stale_app_version_headings
from lib.upgradedoc.consistency_checks import find_changes_row_correspondence_gaps
from lib.upgradedoc.removed_items import removed_component_image_names
from lib.upgradedoc.sorting_and_ordering import OrderingContext
from lib.upgradedoc.sorting_and_ordering import parse_upgrade_doc_changes_blocks
from lib.upgradedoc.sorting_and_ordering import sort_changes_blocks
from lib.upgradedoc.sorting_and_ordering import sort_upgrade_doc_rows
from lib.upgradedoc.sorting_and_ordering import sort_values_delta_sections
from lib.upgradedoc.string_and_parsing_basics import parse_upgrade_doc_rows


def _remove_unchanged_component_rows(text: str, upgrade_path: Path, state: RebaseState) -> tuple[str, bool]:
    """Remove rows (and Changes sections) unchanged vs baseline. Returns (text, changed)."""
    text, removed_names = remove_unchanged_component_rows(text, state.resolution)
    print_section_items(
        f"Removing unchanged component row(s) + Changes section(s) from {upgrade_path.name}",
        [f"{name} (same app and chart version as {state.new_baseline})" for name in removed_names],
    )
    return text, bool(removed_names)


def _correct_component_table(text: str, upgrade_path: Path, state: RebaseState):
    """Fix wrong app/chart cells in the Component versions table. Returns (text, changed)."""
    new_baseline = state.new_baseline
    text, changed_rows, unmatched_names, unresolved_names = fix_component_version_table(text, state.resolution)
    # Removed items' rows are written by _sync_removed_items.
    removed_names = {item.name for item in state.removed_items_ordering[0]}
    unmatched_names = [name for name in unmatched_names if name not in removed_names]
    unresolved_names = [name for name in unresolved_names if name not in removed_names]
    if changed_rows:
        print_section(f"Correcting component version table in {upgrade_path.name}")
        for name, app_cell, chart_cell in changed_rows:
            print(f"  {name}: app {app_cell}  |  chart {chart_cell}")
    if unresolved_names:
        print()
        print(
            f"Could not verify source version for {len(unresolved_names)} component(s) in "
            f"{upgrade_path.name} — baseline {new_baseline} doesn't resolve to a git ref, "
            f"or the component didn't exist there yet. Table left as-is for these; review "
            f"by hand."
        )
        for name in unresolved_names:
            print(f"  {name}")
    if unmatched_names:
        print()
        print(
            f"Could not match {len(unmatched_names)} component(s) in {upgrade_path.name} "
            f"to a Chart.yaml dependency, left as-is:"
        )
        for name in unmatched_names:
            print(f"  {name}")
    return text, bool(changed_rows)


def _add_missing_component_and_sidecar_rows(
    text: str, state: RebaseState, upgrade_path: Path, actual_changed_keys: set[str]
) -> tuple[str, list[str], list[str]]:
    """Add rows and Changes sections for changed components/sidecars. Returns (text, added, added_sidecars)."""
    doc_ctx = DocContext(state.paths.chart_dir, state.target, upgrade_docs_baseline=state.new_baseline)
    text, added_names = add_missing_component_rows(text, doc_ctx, state.resolution, actual_changed_keys)
    print_section_items(
        f"Adding missing component row(s) + Changes section(s) to {upgrade_path.name}",
        [f"{name}" for name in added_names],
    )

    if state.baseline_deps is None:
        return text, added_names, []

    text, added_sidecar_names = add_missing_sidecar_rows(
        text, doc_ctx, state.target_state, state.baseline_values, state.image_indexes
    )
    print_section_items(
        f"Adding missing sidecar/shared-image row(s) + Changes section(s) to {upgrade_path.name}",
        [f"{name}" for name in added_sidecar_names],
    )
    return text, added_names, added_sidecar_names


def _fix_upgrade_doc_headings(text: str, state: RebaseState, upgrade_path: Path) -> tuple[str, bool]:
    """Add missing '### ...' sections and fix heading app versions. Returns (text, changed)."""
    canonical_names = state.resolution.target_index.canonical_names

    doc_context = DocContext(state.paths.chart_dir, state.target)
    ordering = OrderingContext(state.target_deps, state.target_values, canonical_names)
    text, added = add_missing_changes_sections(
        text, state.target_deps, state.target_values, doc_context, canonical_names
    )
    print_section_items(f"Adding missing '### ...' Changes section(s) in {upgrade_path.name}", added)
    text, stale = update_stale_app_version_headings(text, doc_context, ordering)
    print_section_items(
        f"Updating '### ...' Changes section(s) missing their app version in {upgrade_path.name}", stale
    )
    text, rebuilt = rebuild_changes_sections_contradicting_rows(text, doc_context, ordering)
    print_section_items(
        f"Rebuilding '### ...' Changes section(s) that contradict their table row in {upgrade_path.name}",
        [f"'### {section.heading}' -> '### {section.expected_heading}'" for section in rebuilt],
    )
    text, wrong = fix_changes_heading_app_versions(text, state.resolution)
    print_section_items(
        "Correcting '### ...' Changes section heading(s) with the wrong name/app-version transition "
        f"in {upgrade_path.name}",
        wrong,
    )
    return text, bool(added or stale or rebuilt or wrong)


def _add_missing_pin_bullets(text: str, upgrade_path: Path, state: RebaseState) -> tuple[str, bool]:
    """Add a pin bullet for each path sharing a YAML anchor with a documented one. Returns (text, changed)."""
    text, added = add_missing_pin_bullets(text, alias_groups(state.paths.values_yaml), state.baseline_values)
    items = [
        f"'### {missing.heading}': {missing.missing_path} (shares an anchor with {missing.documented_path})"
        for missing in added
    ]
    print_section_items(f"Adding pin bullet(s) for paths sharing a YAML anchor in {upgrade_path.name}", items)
    return text, bool(items)


def _fix_pointer_issues(text: str, upgrade_path: Path, state: RebaseState) -> tuple[str, bool]:
    """Add a missing "- Image / digest" pointer and the blank line before it. Returns (text, changed)."""
    headings = [block["heading"] for block in parse_upgrade_doc_changes_blocks(text)]
    items, _ordering = state.removed_items_ordering
    _rows_without_heading, rowless_headings = find_changes_row_correspondence_gaps(
        parse_upgrade_doc_rows(text),
        headings,
        state.target_deps,
        state.resolution.target_index.canonical_names,
        {item.name: item for item in items},
    )
    text, fixed = fix_pointer_issues(text, state.target, rowless_headings)
    items = [f"'### {issue.heading}': {issue.kind.replace('-', ' ')}" for issue in fixed]
    print_section_items(f"Fixing the image digest pointer in {upgrade_path.name}", items)
    return text, bool(items)


def _sync_removed_items(text: str, state: RebaseState, upgrade_path: Path) -> tuple[str, bool]:
    """Add or rewrite the rows and Changes sections of removed components/images. Returns (text, changed)."""
    items, ordering = state.removed_items_ordering
    gone_row_names = (
        removed_component_image_names(state.resolution.target_index, state.baseline_index)
        if state.baseline_index is not None
        else set[str]()
    )
    text, synced = sync_removed_items(text, items, state.target, ordering, gone_row_names)
    print_section_items(
        f"Adding or updating removed component/image row(s) + Changes section(s) in {upgrade_path.name}", synced
    )
    return text, bool(synced)


def _reorder_upgrade_doc(text: str, upgrade_path: Path, state: RebaseState):
    """Order table rows and Changes blocks like values.yaml. Returns (text, changed)."""
    _items, ordering = state.removed_items_ordering
    text, moved_rows = sort_upgrade_doc_rows(text, ordering)
    text, moved_blocks = sort_changes_blocks(text, ordering)
    if moved_rows or moved_blocks:
        print_section(f"Reordering {upgrade_path.name} to match values.yaml's component order")
        for name, old_pos, new_pos in moved_rows:
            print(f"  table row '{name}': position {old_pos} -> {new_pos}")
        for heading, old_pos, new_pos in moved_blocks:
            print(f"  changes block '### {heading}': position {old_pos} -> {new_pos}")
    return text, bool(moved_rows or moved_blocks)


def _retarget_heading_links(original: str, text: str, doc_path: Path):
    """Point links at the headings this run renamed in `doc_path`. Returns (text, changed)."""
    text, retargeted = retarget_heading_links(original, text)
    print_section_items(f"Updating link(s) to renamed heading(s) in {doc_path.name}", retargeted)
    return text, bool(retargeted)


def fix_upgrade_doc_content(state: RebaseState, upgrade_path: Path, actual_changed_keys: set[str]):
    """Fix the upgrade doc; writes only if something changed."""
    if not upgrade_path.is_file():
        return
    original = upgrade_path.read_text(encoding="utf-8")
    text = original

    changed: list[bool] = []
    text, step_changed = _remove_unchanged_component_rows(text, upgrade_path, state)
    changed.append(step_changed)
    # Before the table check, so a stale removed row is gone instead of reported as unmatched.
    text, step_changed = _sync_removed_items(text, state, upgrade_path)
    changed.append(step_changed)
    text, step_changed = _correct_component_table(text, upgrade_path, state)
    changed.append(step_changed)
    text, added_names, added_sidecar_names = _add_missing_component_and_sidecar_rows(
        text, state, upgrade_path, actual_changed_keys
    )
    changed += [bool(added_names), bool(added_sidecar_names)]
    text, step_changed = _fix_upgrade_doc_headings(text, state, upgrade_path)
    changed.append(step_changed)
    text, step_changed = _add_missing_pin_bullets(text, upgrade_path, state)
    changed.append(step_changed)
    text, step_changed = _fix_pointer_issues(text, upgrade_path, state)
    changed.append(step_changed)
    text, step_changed = _reorder_upgrade_doc(text, upgrade_path, state)
    changed.append(step_changed)
    text, step_changed = _retarget_heading_links(original, text, upgrade_path)
    changed.append(step_changed)

    # Also collapse double blank lines that predate this run.
    collapsed_text = collapse_multiple_blank_lines(text)
    if collapsed_text != text:
        changed.append(True)
        print_section(f"Collapsing multiple consecutive blank line(s) in {upgrade_path.name}")

    if any(changed):
        upgrade_path.write_text(collapsed_text, encoding="utf-8")


def _fix_values_delta_headings(text: str, state: RebaseState, upgrade_path: Path, values_deltas_path: Path):
    """Align '## ...' headings with the (already fixed) upgrade doc table. Returns (text, changed)."""
    upgrade_doc_text = upgrade_path.read_text(encoding="utf-8") if upgrade_path.is_file() else ""
    text, updated_delta_headings = fix_values_delta_heading_app_versions(
        upgrade_doc_text,
        text,
        state.resolution,
    )
    if updated_delta_headings:
        print_section(
            f"Correcting '## ...' section heading(s) with the wrong name/app-version "
            f"transition in {values_deltas_path.name}"
        )
        for heading in updated_delta_headings:
            print(f"  {heading}")
    return text, bool(updated_delta_headings)


def _prune_empty_values_delta_sections(text: str, values_deltas_path: Path):
    """Remove empty '## ...' sections. Returns (text, changed)."""
    text, pruned_headings = prune_empty_values_delta_sections(text)
    print_section_items(
        f"Removing empty section(s) from {values_deltas_path.name}", [f"'## {heading}'" for heading in pruned_headings]
    )
    return text, bool(pruned_headings)


def _sort_values_delta_sections(
    text: str, state: RebaseState, values_deltas_path: Path, canonical_names: dict[str, ValuesPath]
):
    """Order '## ...' sections like values.yaml. Returns (text, changed)."""
    text, moved_sections = sort_values_delta_sections(
        text, OrderingContext(state.target_deps, state.target_values, canonical_names)
    )
    if moved_sections:
        print_section(f"Reordering {values_deltas_path.name} to match values.yaml's component order")
        for heading, old_pos, new_pos in moved_sections:
            print(f"  '## {heading}': position {old_pos} -> {new_pos}")
    return text, bool(moved_sections)


def fix_values_deltas_content(state: RebaseState, upgrade_path: Path, values_deltas_path: Path):
    """Fix the values-deltas doc; writes only if something changed."""
    if not values_deltas_path.is_file():
        return

    original = values_deltas_path.read_text(encoding="utf-8")
    text = original
    canonical_names = state.resolution.target_index.canonical_names

    text, headings_changed = _fix_values_delta_headings(text, state, upgrade_path, values_deltas_path)
    text, pruned = _prune_empty_values_delta_sections(text, values_deltas_path)
    text, reordered = _sort_values_delta_sections(text, state, values_deltas_path, canonical_names)
    text, links_retargeted = _retarget_heading_links(original, text, values_deltas_path)

    collapsed_text = collapse_multiple_blank_lines(text)
    blank_lines_fixed = collapsed_text != text
    if blank_lines_fixed:
        print_section(f"Collapsing multiple consecutive blank line(s) in {values_deltas_path.name}")

    if any([headings_changed, pruned, reordered, links_retargeted, blank_lines_fixed]):
        values_deltas_path.write_text(collapsed_text, encoding="utf-8")
