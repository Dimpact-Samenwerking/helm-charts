"""fix-doc-consistency's repairs of an images manifest."""

from pathlib import Path

from lib.chart.values_tree_primitives import ValuesPath
from lib.cli import print_section
from lib.cli import print_section_items
from lib.component_docs.images_manifest_changes_header import renumber_images_manifest_changes_items
from lib.fix_doc_consistency.manifest_changes_items import correct_stale_changes_items
from lib.fix_doc_consistency.manifest_changes_items import dedupe_images_manifest_changes_items
from lib.fix_doc_consistency.manifest_changes_items import sort_images_manifest_changes_items
from lib.fix_doc_consistency.manifest_entries_core import BaselineRelease
from lib.fix_doc_consistency.manifest_entries_core import ManifestEntriesContext
from lib.fix_doc_consistency.manifest_entries_core import fix_images_manifest_entries
from lib.fix_doc_consistency.manifest_entries_new_and_removed import add_missing_images_manifest_entries
from lib.fix_doc_consistency.manifest_entries_new_and_removed import remove_removed_images_manifest_entries
from lib.fix_doc_consistency.manifest_entries_new_and_removed import remove_stale_images_manifest_entries
from lib.fix_doc_consistency.manifest_entry_urls_and_names import fix_images_manifest_entry_names
from lib.fix_doc_consistency.manifest_entry_urls_and_names import fix_images_manifest_entry_urls
from lib.fix_doc_consistency.rebase_state import RebaseState
from lib.image.manifest_entry_pins import sync_entry_pins
from lib.settings import digest_pinning_exceptions
from lib.upgradedoc.images_manifest_ordering import ManifestSortContext
from lib.upgradedoc.images_manifest_ordering import images_manifest_display_name_positions
from lib.upgradedoc.images_manifest_ordering import sort_images_manifest_entries
from lib.upgradedoc.sorting_and_ordering import MovedItem


def _correct_images_manifest_names(images_path: Path, repo_map: dict[str, ValuesPath]):
    """Renames an entry whose "name:" isn't its url minus the registry
    host (e.g. "python" for docker.io/library/python)."""
    text = images_path.read_text(encoding="utf-8")
    new_text, renamed = fix_images_manifest_entry_names(text, repo_map)
    if renamed:
        images_path.write_text(new_text, encoding="utf-8")
        print_section(f"Correcting entry name(s) in {images_path.name}")
        for old_name, new_name in renamed:
            print(f"  {old_name} -> {new_name}")


def _sync_images_manifest_entry_pins(images_path: Path, state: RebaseState) -> None:
    """Sets each entry's version/digest to the tag values.yaml pins."""
    text = images_path.read_text(encoding="utf-8")
    new_text, synced = sync_entry_pins(
        text, state.resolution.target_index, digest_pinning_exceptions(state.paths.chart_dir)
    )
    if synced:
        images_path.write_text(new_text, encoding="utf-8")
        print_section(f"Syncing entry version/digest in {images_path.name} with values.yaml")
        for name in synced:
            print(f"  {name}")


def _correct_images_manifest_entries(images_path: Path, state: RebaseState, repo_map: dict[str, ValuesPath]):
    """Correct entry comments (source -> target version)."""
    text = images_path.read_text(encoding="utf-8")
    new_text, changed_entries, unresolved_entry_names = fix_images_manifest_entries(
        text,
        ManifestEntriesContext(
            state.paths.chart_dir,
            state.target_deps,
            state.target_values,
            state.baseline_values,
            repo_map,
            baseline_release=BaselineRelease(state.new_baseline, state.baseline_deps),
        ),
    )
    if changed_entries:
        images_path.write_text(new_text, encoding="utf-8")
        print_section(f"Correcting entry comments in {images_path.name}")
        for name, source, target_ver in changed_entries:
            print(f"  {name}: {source} -> {target_ver}")
    if unresolved_entry_names:
        print()
        print(
            f"Could not verify source/target version for {len(unresolved_entry_names)} "
            f"entry(s) in {images_path.name} — no preceding comment, unresolvable "
            f"values-tree path, or baseline {state.new_baseline} doesn't resolve to a git ref. "
            f"Left as-is; review by hand."
        )
        for name in unresolved_entry_names:
            print(f"  {name}")


def _correct_images_manifest_urls(images_path: Path, state: RebaseState, repo_map: dict[str, ValuesPath]):
    """Corrects images-manifest entry url(s)."""
    text = images_path.read_text(encoding="utf-8")
    new_text, changed_urls, unresolved_url_names = fix_images_manifest_entry_urls(
        text, state.paths.chart_dir, state.target_deps, state.target_values, repo_map
    )
    if changed_urls:
        images_path.write_text(new_text, encoding="utf-8")
        print_section(f"Correcting entry url(s) in {images_path.name}")
        for name, old_url, new_url in changed_urls:
            print(f"  {name}: {old_url} -> {new_url}")
    if unresolved_url_names:
        print()
        print(
            f"Could not verify the fully host-qualified url for {len(unresolved_url_names)} "
            f"entry(s) in {images_path.name} — unresolvable values-tree path or repository. "
            f"Left as-is; review by hand."
        )
        for name in unresolved_url_names:
            print(f"  {name}")


def _remove_stale_images_manifest_entries(images_path: Path, state: RebaseState):
    """Remove entries (with comment and '# Changes:' item) unchanged vs baseline."""
    if not state.baseline_values:
        return
    text = images_path.read_text(encoding="utf-8")
    new_text, removed_entry_names = remove_stale_images_manifest_entries(text, state.missing_entries_context)
    if removed_entry_names:
        images_path.write_text(new_text, encoding="utf-8")
        print_section(f"Removing unchanged entr(y/ies) from {images_path.name}")
        for name in removed_entry_names:
            print(f"  {name} (same version and digest as {state.new_baseline})")


def _remove_removed_images_manifest_entries(images_path: Path, state: RebaseState):
    """Remove entries (with comment and '# Changes:' item) of images the target no longer has."""
    if state.baseline_index is None or not state.removed_image_paths:
        return
    text = images_path.read_text(encoding="utf-8")
    new_text, removed_entry_names = remove_removed_images_manifest_entries(
        text, state.missing_entries_context, state.baseline_index, state.removed_image_paths
    )
    if removed_entry_names:
        images_path.write_text(new_text, encoding="utf-8")
        print_section(f"Removing entr(y/ies) of removed images from {images_path.name}")
        for name in removed_entry_names:
            print(f"  {name} (not in {state.target})")


def _add_missing_images_manifest_entries(images_path: Path, state: RebaseState):
    """Add entries for changed images and backfill missing '# Changes:' items."""
    if not state.baseline_values:
        return
    text = images_path.read_text(encoding="utf-8")
    ctx = state.missing_entries_context
    new_text, added_entry_names, skipped_entry_names, backfilled_header_names = add_missing_images_manifest_entries(
        text, ctx
    )
    if added_entry_names:
        images_path.write_text(new_text, encoding="utf-8")
        print_section(f"Adding missing entr(y/ies) to {images_path.name}")
        for name in added_entry_names:
            print(f"  {name} (review 'name:' for the correct ACR mirror slug)")
    if skipped_entry_names:
        print()
        print(
            f"Could not add an entry for {len(skipped_entry_names)} changed image(s) in "
            f"{images_path.name} — no resolvable repository, or its values.yaml tag has no "
            f"digest pinned yet. Add by hand."
        )
        for name in skipped_entry_names:
            print(f"  {name}")
    if backfilled_header_names:
        images_path.write_text(new_text, encoding="utf-8")
        print_section(f"Adding missing '# Changes:' header item(s) to {images_path.name}")
        for name in backfilled_header_names:
            print(f"  {name} (entry already existed — only its header item was missing)")


def _fix_stale_changes_items(
    images_path: Path, state: RebaseState, upgrade_path: Path, canonical_names: dict[str, ValuesPath]
) -> None:
    """Rewrite '# Changes:' items that contradict their upgrade-doc table row."""
    fixed = correct_stale_changes_items(images_path, upgrade_path, canonical_names, state.resolution)
    print_section_items(
        f"Correcting '# Changes:' item(s) in {images_path.name}", [f"{old}  ->  {new}" for old, new in fixed]
    )


def _dedupe_images_manifest_changes_items(images_path: Path):
    """Removes a duplicate '# Changes:' header item."""
    lines = images_path.read_text(encoding="utf-8").splitlines(keepends=True)
    removed_duplicate_items = dedupe_images_manifest_changes_items(lines)
    if removed_duplicate_items:
        images_path.write_text("".join(lines), encoding="utf-8")
        print_section(f"Removing duplicate '# Changes:' header item(s) from {images_path.name}")
        for item_text in removed_duplicate_items:
            print(f"  {item_text}")


def _reorder_manifest_text(
    before_sort: str, sort_context: ManifestSortContext
) -> tuple[str, list[MovedItem], list[MovedItem]]:
    """Reordered text without writing. Returns (text, moved_header_items, moved_entries)."""
    display_name_positions = images_manifest_display_name_positions(before_sort, sort_context)
    lines = before_sort.splitlines(keepends=True)
    moved_header_items = sort_images_manifest_changes_items(lines, display_name_positions)
    text = "".join(lines)
    text, moved_entries = sort_images_manifest_entries(text, sort_context)
    return text, moved_header_items, moved_entries


def _sort_images_manifest(
    images_path: Path, state: RebaseState, repo_map: dict[str, ValuesPath], canonical_names: dict[str, ValuesPath]
):
    """Order entries and '# Changes:' items like values.yaml."""
    before_sort = images_path.read_text(encoding="utf-8")
    sort_context = ManifestSortContext(state.target_deps, state.target_values, repo_map, canonical_names)
    text, moved_header_items, moved_entries = _reorder_manifest_text(before_sort, sort_context)
    if text == before_sort:
        return
    images_path.write_text(text, encoding="utf-8")
    print_section(f"Reordering {images_path.name} to match values.yaml's component order")
    for item_text, old_pos, new_pos in moved_header_items:
        print(f"  '# Changes:' item {old_pos} -> {new_pos}: {item_text}")
    for name, old_pos, new_pos in moved_entries:
        print(f"  entry '{name}': position {old_pos} -> {new_pos}")
    if not moved_header_items and not moved_entries:
        print("  (blank lines within group(s) tidied)")


def _renumber_images_manifest_changes_items(images_path: Path):
    """Renumber the '# Changes:' list; sorting only fixes relative order."""
    lines = images_path.read_text(encoding="utf-8").splitlines(keepends=True)
    if renumber_images_manifest_changes_items(lines):
        images_path.write_text("".join(lines), encoding="utf-8")
        print_section(f"Renumbering '# Changes:' list in {images_path.name}")


def fix_images_manifest_content(state: RebaseState, images_path: Path, upgrade_path: Path):
    """Fix images manifest entries and its '# Changes:' list.

    URLs are fixed before names so a corrected URL yields the name in the same run.
    """
    if not images_path.is_file():
        return
    index = state.resolution.target_index
    repo_map, canonical_names = index.repo_map, index.canonical_names

    _correct_images_manifest_urls(images_path, state, repo_map)
    _correct_images_manifest_names(images_path, repo_map)
    _sync_images_manifest_entry_pins(images_path, state)
    _remove_stale_images_manifest_entries(images_path, state)
    _remove_removed_images_manifest_entries(images_path, state)
    _correct_images_manifest_entries(images_path, state, repo_map)
    _add_missing_images_manifest_entries(images_path, state)
    # Correct before deduping: a stale copy ("1.1.0 -> 1.1.3") only becomes a
    # duplicate of the current item ("1.1.0 -> 1.1.4") once corrected.
    _fix_stale_changes_items(images_path, state, upgrade_path, canonical_names)
    _dedupe_images_manifest_changes_items(images_path)
    _sort_images_manifest(images_path, state, repo_map, canonical_names)
    _renumber_images_manifest_changes_items(images_path)
