"""fix-doc-consistency's pipeline: rebase the upgrade docs of a target onto its baseline and repair their content.

fix_docs writes the docs under FixDocPaths. The script runs it on the real
docs; check_docs_consistency runs it on a copy and reports the difference.
"""

import sys

from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path

from lib.chart.chart_state import BaselineState
from lib.chart.chart_state import ComponentState
from lib.chart.chart_yaml import ChartDependency
from lib.chart.chart_yaml import load_chart_dependencies
from lib.chart.chart_yaml import parse_chart_dependencies
from lib.chart.yaml_alias_groups import alias_groups
from lib.cli import print_section
from lib.cli import print_section_items
from lib.component_docs.aliased_pin_bullets import add_missing_pin_bullets
from lib.component_docs.baseline_doc_stubs import IMAGES_STUB_TEMPLATE
from lib.component_docs.baseline_doc_stubs import STUB_TEMPLATES
from lib.component_docs.baseline_doc_stubs import existing_doc_baselines
from lib.component_docs.changes_section import DocContext
from lib.component_docs.changes_section import add_missing_component_rows
from lib.component_docs.changes_section import fix_pointer_issues
from lib.component_docs.changes_section import strip_stale_upgrade_placeholders
from lib.component_docs.images_manifest_changes_header import renumber_images_manifest_changes_items
from lib.component_docs.removed_item_docs import sync_removed_items
from lib.component_docs.values_delta_sections import prune_empty_values_delta_sections
from lib.component_docs.values_delta_sections import strip_stale_values_deltas_todo_stub
from lib.component_docs.values_delta_sections import sync_values_delta_sections
from lib.fix_doc_consistency.baseline_and_images_manifest_handling import extract_images_baseline
from lib.fix_doc_consistency.baseline_and_images_manifest_handling import fix_images_manifest_header_lines
from lib.fix_doc_consistency.baseline_and_images_manifest_handling import update_sibling_doc_refs
from lib.fix_doc_consistency.component_version_table import fix_changes_heading_app_versions
from lib.fix_doc_consistency.component_version_table import fix_component_version_table
from lib.fix_doc_consistency.component_version_table import fix_values_delta_heading_app_versions
from lib.fix_doc_consistency.component_version_table import remove_unchanged_component_rows
from lib.fix_doc_consistency.manifest_changes_items import correct_stale_changes_items
from lib.fix_doc_consistency.manifest_changes_items import dedupe_images_manifest_changes_items
from lib.fix_doc_consistency.manifest_changes_items import sort_images_manifest_changes_items
from lib.fix_doc_consistency.manifest_entries_core import ManifestEntriesContext
from lib.fix_doc_consistency.manifest_entries_core import fix_images_manifest_entries
from lib.fix_doc_consistency.manifest_entries_new_and_urls import MissingEntriesContext
from lib.fix_doc_consistency.manifest_entries_new_and_urls import add_missing_images_manifest_entries
from lib.fix_doc_consistency.manifest_entries_new_and_urls import fix_images_manifest_entry_names
from lib.fix_doc_consistency.manifest_entries_new_and_urls import fix_images_manifest_entry_urls
from lib.fix_doc_consistency.manifest_entries_new_and_urls import remove_stale_images_manifest_entries
from lib.fix_doc_consistency.text_helpers_and_repo_rename import collapse_multiple_blank_lines
from lib.fix_doc_consistency.text_helpers_and_repo_rename import find_collisions
from lib.fix_doc_consistency.text_helpers_and_repo_rename import git_mv
from lib.fix_doc_consistency.text_helpers_and_repo_rename import join_and
from lib.fix_doc_consistency.text_helpers_and_repo_rename import remaining_mentions
from lib.fix_doc_consistency.text_helpers_and_repo_rename import update_component_versions_heading
from lib.fix_doc_consistency.text_helpers_and_repo_rename import update_title_line
from lib.gitutil import baseline_ref_candidates
from lib.gitutil import find_repo_root
from lib.gitutil import git_show_text
from lib.gitutil import git_show_yaml
from lib.gitutil import resolve_git_ref
from lib.image.docs import add_missing_changes_sections
from lib.image.docs import add_missing_sidecar_rows
from lib.image.docs import rebuild_changes_sections_contradicting_rows
from lib.image.docs import update_stale_app_version_headings
from lib.image.manifest_entry_pins import sync_entry_pins
from lib.settings import digest_pinning_exceptions
from lib.upgradedoc.app_version_and_image_paths import ImagePath
from lib.upgradedoc.chart_image_index import ChartImageIndex
from lib.upgradedoc.doc_names import STANDARD_SUFFIXES
from lib.upgradedoc.doc_names import doc_name
from lib.upgradedoc.doc_names import images_manifest_path
from lib.upgradedoc.images_manifest_list_diff import compute_changed_components
from lib.upgradedoc.images_manifest_ordering import ManifestSortContext
from lib.upgradedoc.images_manifest_ordering import images_manifest_display_name_positions
from lib.upgradedoc.images_manifest_ordering import sort_images_manifest_entries
from lib.upgradedoc.removed_items import RemovedItem
from lib.upgradedoc.removed_items import removed_items
from lib.upgradedoc.resolve_component_row import ResolutionContext
from lib.upgradedoc.sorting_and_ordering import OrderingContext
from lib.upgradedoc.sorting_and_ordering import sort_changes_blocks
from lib.upgradedoc.sorting_and_ordering import sort_upgrade_doc_rows
from lib.upgradedoc.sorting_and_ordering import sort_values_delta_sections
from lib.yaml_types import YamlMapping
from lib.yaml_types import load_yaml_mapping


@dataclass(frozen=True)
class FixDocPaths:
    """Where fix_docs reads the chart and reads and writes the docs.

    `rename` moves a doc to its new baseline name: git mv for the real docs,
    a plain rename for a copy outside the repository.
    """

    chart_dir: Path
    doc_dir: Path
    images_dir: Path
    rename: Callable[[Path, Path], None] = field(default=git_mv)

    @property
    def chart_yaml(self) -> Path:
        """The chart's Chart.yaml."""
        return self.chart_dir / "Chart.yaml"

    @property
    def values_yaml(self) -> Path:
        """The chart's values.yaml."""
        return self.chart_dir / "values.yaml"


def load_target_state(paths: FixDocPaths):
    """(deps, values) from Chart.yaml and values.yaml on disk."""
    values = load_yaml_mapping(paths.values_yaml)
    return load_chart_dependencies(paths.chart_yaml), values


def load_baseline_state(
    paths: FixDocPaths, new_baseline: str
) -> tuple[list[ChartDependency], YamlMapping] | tuple[None, None]:
    """(deps, values) at new_baseline's git ref, or (None, None) if it does not resolve."""
    repo_root = find_repo_root(paths.chart_dir)
    if repo_root is None:
        return None, None
    ref = resolve_git_ref(repo_root, baseline_ref_candidates(new_baseline))
    if ref is None:
        return None, None
    rel_chart_dir = paths.chart_dir.relative_to(repo_root)
    baseline_chart_text = git_show_text(repo_root, ref, f"{rel_chart_dir}/Chart.yaml")
    if baseline_chart_text is None:
        return None, None
    baseline_values = git_show_yaml(repo_root, ref, f"{rel_chart_dir}/values.yaml") or {}
    return parse_chart_dependencies(baseline_chart_text, f"{ref}:{rel_chart_dir}/Chart.yaml"), baseline_values


@dataclass
class RebaseState:
    """Target/baseline versions and their dependency/values trees."""

    paths: FixDocPaths
    target: str
    new_baseline: str
    target_deps: list[ChartDependency]
    target_values: YamlMapping
    baseline_deps: list[ChartDependency] | None
    baseline_values: YamlMapping | None

    @property
    def target_state(self) -> ComponentState:
        """Chart.yaml and values.yaml of the target."""
        return ComponentState(self.target_deps, self.target_values)

    @property
    def baseline_state(self) -> BaselineState:
        """Chart.yaml and values.yaml at the baseline."""
        return BaselineState(self.baseline_deps, self.baseline_values)

    @property
    def resolution(self) -> ResolutionContext:
        """The resolve_component_row inputs every doc step shares."""
        return ResolutionContext(
            self.paths.chart_dir, self.target_state, self.baseline_state, upgrade_docs_baseline=self.new_baseline
        )


def _check_no_collisions(paths: FixDocPaths, target: str) -> dict[str, list[tuple[str, Path]]]:
    """Existing docs by suffix; exits if two would rename to the same file."""
    by_suffix = existing_doc_baselines(paths.doc_dir, target)
    collisions = find_collisions(by_suffix)
    if not collisions:
        return by_suffix
    print(f"error: multiple source docs would collide on the same target for '{target}':")
    for suffix, entries in sorted(collisions.items()):
        print(f"  {suffix}:")
        for baseline, path in sorted(entries):
            print(f"    {path.name}  (baseline {baseline})")
    print()
    print("Refusing to rename anything — resolve the collision above first.")
    sys.exit(1)


@dataclass
class DocRename:
    """A doc being rebased."""

    path: Path
    old_baseline: str
    suffix: str


@dataclass
class RebaseAccumulator:
    """Findings collected across all docs."""

    todo_stub_docs: list[str]
    # (doc name, line numbers still naming the old baseline)
    review_notes: list[tuple[str, list[int]]]


def _rebase_already_at_baseline(doc: DocRename, target: str, new_baseline: str, acc: RebaseAccumulator):
    """Fix stale sibling refs, TODO stubs and double blank lines in a doc already at new_baseline."""
    text = doc.path.read_text(encoding="utf-8")
    text, refs_changed = update_sibling_doc_refs(text, target, new_baseline)
    todo_stripped = False
    if doc.suffix == "upgrade":
        text, todo_stripped = strip_stale_upgrade_placeholders(text)
    elif doc.suffix == "values-deltas":
        text, todo_stripped = strip_stale_values_deltas_todo_stub(text)
    collapsed_text = collapse_multiple_blank_lines(text)
    blank_lines_fixed = collapsed_text != text
    if not (refs_changed or blank_lines_fixed or todo_stripped):
        print(f"  {doc.path.name}: already baseline {new_baseline} — unchanged")
        return
    doc.path.write_text(collapsed_text, encoding="utf-8")
    parts: list[str] = []
    if todo_stripped:
        parts.append("removed stale TODO placeholder")
        acc.todo_stub_docs.append(doc.path.name)
    if refs_changed:
        parts.append("fixed stale sibling doc reference(s)")
    if blank_lines_fixed:
        parts.append("collapsed multiple blank line(s)")
    print(f"  {doc.path.name}: already baseline {new_baseline} — {join_and(parts)}")


def _rebase_doc_to_new_baseline(
    paths: FixDocPaths, doc: DocRename, target: str, new_baseline: str, acc: RebaseAccumulator
):
    """Rename doc onto new_baseline and rewrite its title, heading, refs and stubs."""
    new_name = doc_name(new_baseline, target, doc.suffix)
    new_path = paths.doc_dir / new_name
    text = doc.path.read_text(encoding="utf-8")

    text, title_changed = update_title_line(text, doc.old_baseline, target, new_baseline)
    text, heading_changed = update_component_versions_heading(text, doc.old_baseline, target, new_baseline)
    text, refs_changed = update_sibling_doc_refs(text, target, new_baseline)
    todo_stripped = False
    if doc.suffix == "upgrade":
        text, todo_stripped = strip_stale_upgrade_placeholders(text)
    elif doc.suffix == "values-deltas":
        text, todo_stripped = strip_stale_values_deltas_todo_stub(text)

    if doc.path != new_path:
        paths.rename(doc.path, new_path)
    new_path.write_text(collapse_multiple_blank_lines(text), encoding="utf-8")

    print(f"  {doc.path.name} -> {new_name}")
    if title_changed:
        print(f"    title line: {doc.old_baseline} -> {new_baseline}")
    if heading_changed:
        print(f"    'Component versions' heading: {doc.old_baseline} -> {new_baseline}")
    if refs_changed:
        print(f"    sibling doc references: -> {new_baseline}-to-{target}-*.md")
    if todo_stripped:
        print("    removed stale TODO placeholder")
        acc.todo_stub_docs.append(new_name)

    leftovers = remaining_mentions(text, doc.old_baseline)
    if leftovers:
        acc.review_notes.append((new_name, leftovers))


def _rebase_docs(
    paths: FixDocPaths, target: str, new_baseline: str, by_suffix: dict[str, list[tuple[str, Path]]]
) -> tuple[list[tuple[str, list[int]]], list[str]]:
    """Rebase every doc onto new_baseline, stubbing missing ones. Returns (review_notes, todo_stub_docs)."""
    acc = RebaseAccumulator(todo_stub_docs=[], review_notes=[])
    all_suffixes = sorted(set(by_suffix) | set(STANDARD_SUFFIXES))
    for suffix in all_suffixes:
        if suffix not in by_suffix:
            new_name = doc_name(new_baseline, target, suffix)
            new_path = paths.doc_dir / new_name
            new_path.write_text(
                STUB_TEMPLATES[suffix].format(upgrade_docs_baseline=new_baseline, target=target), encoding="utf-8"
            )
            print(f"  {new_name}: created (was missing)")
            continue

        [(old_baseline, path)] = by_suffix[suffix]
        doc = DocRename(path, old_baseline, suffix)
        if old_baseline == new_baseline:
            _rebase_already_at_baseline(doc, target, new_baseline, acc)
            continue

        _rebase_doc_to_new_baseline(paths, doc, target, new_baseline, acc)

    return acc.review_notes, acc.todo_stub_docs


def _bump_images_manifest_baseline(
    paths: FixDocPaths, target: str, new_baseline: str, review_notes: list[tuple[str, list[int]]]
):
    """Stub images-<target>.yaml if missing, else rebase its baseline header and refs. Returns its path."""
    images_path = images_manifest_path(paths.images_dir, target)
    if not images_path.is_file():
        images_path.write_text(
            IMAGES_STUB_TEMPLATE.format(upgrade_docs_baseline=new_baseline, target=target), encoding="utf-8"
        )
        print(f"  {images_path.name}: created (was missing)")
        return images_path

    text = images_path.read_text(encoding="utf-8")
    old_images_baseline = extract_images_baseline(text)
    text, refs_changed = update_sibling_doc_refs(text, target, new_baseline)
    text, baseline_changed = fix_images_manifest_header_lines(text, target, new_baseline)
    if not (refs_changed or baseline_changed):
        print(f"  {images_path.name}: already baseline {new_baseline} — unchanged")
        return images_path
    images_path.write_text(text, encoding="utf-8")
    print(f"  {images_path.name}: baseline updated")
    if refs_changed:
        print(f"    doc references -> {new_baseline}-to-{target}-*.md")
    if baseline_changed:
        print(f"    baseline header line(s): -> {new_baseline}")
    if old_images_baseline and old_images_baseline != new_baseline:
        leftovers = remaining_mentions(text, old_images_baseline)
        if leftovers:
            review_notes.append((images_path.name, leftovers))
    return images_path


def _load_rebase_state(paths: FixDocPaths, target: str, new_baseline: str):
    """RebaseState for the current target and new_baseline."""
    target_deps, target_values = load_target_state(paths)
    baseline_deps, baseline_values = load_baseline_state(paths, new_baseline)
    return RebaseState(paths, target, new_baseline, target_deps, target_values, baseline_deps, baseline_values)


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
    removed_names = {item.name for item in _removed_items_ordering(state)[0]}
    unmatched_names = [name for name in unmatched_names if name not in removed_names]
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
    text, added_names = add_missing_component_rows(
        text, doc_ctx, state.target_state, state.baseline_state, actual_changed_keys
    )
    print_section_items(
        f"Adding missing component row(s) + Changes section(s) to {upgrade_path.name}",
        [f"{name}" for name in added_names],
    )

    if state.baseline_deps is None:
        return text, added_names, []

    text, added_sidecar_names = add_missing_sidecar_rows(text, doc_ctx, state.target_state, state.baseline_values)
    print_section_items(
        f"Adding missing sidecar/shared-image row(s) + Changes section(s) to {upgrade_path.name}",
        [f"{name}" for name in added_sidecar_names],
    )
    return text, added_names, added_sidecar_names


def _fix_upgrade_doc_headings(text: str, state: RebaseState, upgrade_path: Path) -> tuple[str, bool]:
    """Add missing '### ...' sections and fix heading app versions. Returns (text, changed)."""
    canonical_names = ChartImageIndex(state.paths.chart_dir, state.target_deps, state.target_values).canonical_names

    doc_context = DocContext(state.paths.chart_dir, state.target)
    ordering = OrderingContext(state.target_deps, state.target_values, canonical_names)
    text, added = add_missing_changes_sections(
        text, state.target_deps, state.target_values, doc_context, canonical_names
    )
    changed = print_section_items(f"Adding missing '### ...' Changes section(s) in {upgrade_path.name}", added)
    text, stale = update_stale_app_version_headings(text, doc_context, ordering)
    changed |= print_section_items(
        f"Updating '### ...' Changes section(s) missing their app version in {upgrade_path.name}", stale
    )
    text, rebuilt = rebuild_changes_sections_contradicting_rows(text, doc_context, ordering)
    changed |= print_section_items(
        f"Rebuilding '### ...' Changes section(s) that contradict their table row in {upgrade_path.name}",
        [f"'### {s.heading}' -> '### {s.expected_heading}'" for s in rebuilt],
    )
    text, wrong = fix_changes_heading_app_versions(text, state.resolution)
    changed |= print_section_items(
        "Correcting '### ...' Changes section heading(s) with the wrong name/app-version transition "
        f"in {upgrade_path.name}",
        wrong,
    )
    return text, changed


def _add_missing_pin_bullets(text: str, upgrade_path: Path, values_yaml: Path) -> tuple[str, bool]:
    """Add a pin bullet for each path sharing a YAML anchor with a documented one. Returns (text, changed)."""
    text, added = add_missing_pin_bullets(text, alias_groups(values_yaml))
    items = [f"'### {m.heading}': {m.missing_path} (shares an anchor with {m.documented_path})" for m in added]
    return text, print_section_items(
        f"Adding pin bullet(s) for paths sharing a YAML anchor in {upgrade_path.name}", items
    )


def _fix_pointer_issues(text: str, upgrade_path: Path, target: str) -> tuple[str, bool]:
    """Add a missing "- Image / digest" pointer and the blank line before it. Returns (text, changed)."""
    text, fixed = fix_pointer_issues(text, target)
    items = [f"'### {issue.heading}': {issue.kind.replace('-', ' ')}" for issue in fixed]
    return text, print_section_items(f"Fixing the image digest pointer in {upgrade_path.name}", items)


def _removed_items_ordering(state: RebaseState) -> tuple[list[RemovedItem], OrderingContext]:
    """The removed items vs the baseline, and the OrderingContext that places them."""
    target = ChartImageIndex(state.paths.chart_dir, state.target_deps, state.target_values)
    items = (
        removed_items(target, ChartImageIndex(state.paths.chart_dir, state.baseline_deps, state.baseline_values))
        if state.baseline_deps is not None
        else []
    )
    removed_keys = {item.name: item.order_key for item in items}
    return items, OrderingContext(state.target_deps, state.target_values, target.canonical_names, removed_keys)


def _sync_removed_items(text: str, state: RebaseState, upgrade_path: Path) -> tuple[str, bool]:
    """Add or rewrite the rows and Changes sections of removed components/images. Returns (text, changed)."""
    items, ordering = _removed_items_ordering(state)
    text, synced = sync_removed_items(text, items, state.target, ordering)
    return text, print_section_items(
        f"Adding or updating removed component/image row(s) + Changes section(s) in {upgrade_path.name}", synced
    )


def _reorder_upgrade_doc(text: str, upgrade_path: Path, state: RebaseState):
    """Order table rows and Changes blocks like values.yaml. Returns (text, changed)."""
    _items, ordering = _removed_items_ordering(state)
    text, moved_rows = sort_upgrade_doc_rows(text, ordering)
    text, moved_blocks = sort_changes_blocks(text, ordering)
    if moved_rows or moved_blocks:
        print_section(f"Reordering {upgrade_path.name} to match values.yaml's component order")
        for name, old_pos, new_pos in moved_rows:
            print(f"  table row '{name}': position {old_pos} -> {new_pos}")
        for heading, old_pos, new_pos in moved_blocks:
            print(f"  changes block '### {heading}': position {old_pos} -> {new_pos}")
    return text, bool(moved_rows or moved_blocks)


def _fix_upgrade_doc(state: RebaseState, upgrade_path: Path, actual_changed_keys: set[str]):
    """Fix the upgrade doc; writes only if something changed."""
    if not upgrade_path.is_file():
        return
    text = upgrade_path.read_text(encoding="utf-8")

    changed: list[bool] = []
    text, step_changed = _remove_unchanged_component_rows(text, upgrade_path, state)
    changed.append(step_changed)
    text, step_changed = _correct_component_table(text, upgrade_path, state)
    changed.append(step_changed)
    text, added_names, added_sidecar_names = _add_missing_component_and_sidecar_rows(
        text, state, upgrade_path, actual_changed_keys
    )
    changed += [bool(added_names), bool(added_sidecar_names)]
    text, step_changed = _fix_upgrade_doc_headings(text, state, upgrade_path)
    changed.append(step_changed)
    text, step_changed = _add_missing_pin_bullets(text, upgrade_path, state.paths.values_yaml)
    changed.append(step_changed)
    text, step_changed = _fix_pointer_issues(text, upgrade_path, state.target)
    changed.append(step_changed)
    text, step_changed = _sync_removed_items(text, state, upgrade_path)
    changed.append(step_changed)
    text, step_changed = _reorder_upgrade_doc(text, upgrade_path, state)
    changed.append(step_changed)

    # Also collapse double blank lines that predate this run.
    collapsed_text = collapse_multiple_blank_lines(text)
    if collapsed_text != text:
        changed.append(True)
        print_section(f"Collapsing multiple consecutive blank line(s) in {upgrade_path.name}")

    if any(changed):
        upgrade_path.write_text(collapsed_text, encoding="utf-8")


def _correct_images_manifest_names(images_path: Path, repo_map: dict[str, ImagePath]):
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
        text,
        state.paths.chart_dir,
        state.target_deps,
        state.target_values,
        digest_pinning_exceptions(state.paths.chart_dir),
    )
    if synced:
        images_path.write_text(new_text, encoding="utf-8")
        print_section(f"Syncing entry version/digest in {images_path.name} with values.yaml")
        for name in synced:
            print(f"  {name}")


def _correct_images_manifest_entries(images_path: Path, state: RebaseState, repo_map: dict[str, ImagePath]):
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
            upgrade_docs_baseline=state.new_baseline,
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


def _correct_images_manifest_urls(images_path: Path, state: RebaseState, repo_map: dict[str, ImagePath]):
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


def _missing_entries_context(state: RebaseState):
    return MissingEntriesContext(
        state.paths.chart_dir,
        state.target_deps,
        state.target_values,
        state.baseline_values,
        allow_pull=True,
        upgrade_docs_baseline=state.new_baseline,
    )


def _remove_stale_images_manifest_entries(images_path: Path, state: RebaseState):
    """Remove entries (with comment and '# Changes:' item) unchanged vs baseline."""
    if not state.baseline_values:
        return
    text = images_path.read_text(encoding="utf-8")
    new_text, removed_entry_names = remove_stale_images_manifest_entries(text, _missing_entries_context(state))
    if removed_entry_names:
        images_path.write_text(new_text, encoding="utf-8")
        print_section(f"Removing unchanged entr(y/ies) from {images_path.name}")
        for name in removed_entry_names:
            print(f"  {name} (same version and digest as {state.new_baseline})")


def _add_missing_images_manifest_entries(images_path: Path, state: RebaseState):
    """Add entries for changed images and backfill missing '# Changes:' items."""
    if not state.baseline_values:
        return
    text = images_path.read_text(encoding="utf-8")
    ctx = _missing_entries_context(state)
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
    images_path: Path, state: RebaseState, upgrade_path: Path, canonical_names: dict[str, ImagePath]
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
) -> tuple[str, list[tuple[str, int, int]], list[tuple[str, int, int]]]:
    """Reordered text without writing. Returns (text, moved_header_items, moved_entries)."""
    display_name_positions = images_manifest_display_name_positions(before_sort, sort_context)
    lines = before_sort.splitlines(keepends=True)
    moved_header_items = sort_images_manifest_changes_items(lines, display_name_positions)
    text = "".join(lines)
    text, moved_entries = sort_images_manifest_entries(text, sort_context)
    return text, moved_header_items, moved_entries


def _sort_images_manifest(
    images_path: Path, state: RebaseState, repo_map: dict[str, ImagePath], canonical_names: dict[str, ImagePath]
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


def _fix_images_manifest_content(state: RebaseState, images_path: Path, upgrade_path: Path):
    """Fix images manifest entries and its '# Changes:' list.

    URLs are fixed before names so a corrected URL yields the name in the same run.
    """
    if not images_path.is_file():
        return
    index = ChartImageIndex(state.paths.chart_dir, state.target_deps, state.target_values)
    repo_map, canonical_names = index.repo_map, index.canonical_names

    _correct_images_manifest_urls(images_path, state, repo_map)
    _correct_images_manifest_names(images_path, repo_map)
    _sync_images_manifest_entry_pins(images_path, state)
    _remove_stale_images_manifest_entries(images_path, state)
    _correct_images_manifest_entries(images_path, state, repo_map)
    _add_missing_images_manifest_entries(images_path, state)
    _dedupe_images_manifest_changes_items(images_path)
    _fix_stale_changes_items(images_path, state, upgrade_path, canonical_names)
    _sort_images_manifest(images_path, state, repo_map, canonical_names)
    _renumber_images_manifest_changes_items(images_path)


def _sync_values_delta_sections(
    text: str,
    state: RebaseState,
    values_deltas_path: Path,
    changed_keys: set[str],
    canonical_names: dict[str, ImagePath],
):
    """Add missing sections and key-change mentions. Returns (text, changed)."""
    text, created_names, updated_names = sync_values_delta_sections(
        text,
        state.paths.chart_dir,
        OrderingContext(state.target_deps, state.target_values, canonical_names),
        state.baseline_state,
        changed_keys,
    )
    print_section_items(
        f"Adding new component section(s) to {values_deltas_path.name}", [f"{name}" for name in created_names]
    )
    print_section_items(
        f"Adding missing key-change mention(s) to {values_deltas_path.name}", [f"{name}" for name in updated_names]
    )
    return text, bool(created_names or updated_names)


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
    text: str, state: RebaseState, values_deltas_path: Path, canonical_names: dict[str, ImagePath]
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


def _fix_values_deltas(state: RebaseState, upgrade_path: Path, values_deltas_path: Path):
    """Fix the values-deltas doc; writes only if something changed."""
    if not values_deltas_path.is_file():
        return
    if state.baseline_deps is None or state.baseline_values is None:
        print()
        print(
            f"Could not resolve baseline {state.new_baseline} to a git ref — skipping "
            f"added/removed/renamed key detection for {values_deltas_path.name}."
        )
        return

    changed_keys = compute_changed_components(
        state.target_deps, state.baseline_deps, state.target_values, state.baseline_values
    )
    text = values_deltas_path.read_text(encoding="utf-8")
    canonical_names = ChartImageIndex(state.paths.chart_dir, state.target_deps, state.target_values).canonical_names

    text, sections_changed = _sync_values_delta_sections(text, state, values_deltas_path, changed_keys, canonical_names)
    text, headings_changed = _fix_values_delta_headings(text, state, upgrade_path, values_deltas_path)
    text, pruned = _prune_empty_values_delta_sections(text, values_deltas_path)
    text, reordered = _sort_values_delta_sections(text, state, values_deltas_path, canonical_names)

    collapsed_text = collapse_multiple_blank_lines(text)
    blank_lines_fixed = collapsed_text != text
    if blank_lines_fixed:
        print_section(f"Collapsing multiple consecutive blank line(s) in {values_deltas_path.name}")

    if any([sections_changed, headings_changed, pruned, reordered, blank_lines_fixed]):
        values_deltas_path.write_text(collapsed_text, encoding="utf-8")


def fix_docs(paths: FixDocPaths, target: str, new_baseline: str) -> RebaseState:
    """Rebase the docs of `target` onto `new_baseline` and repair their content; prints what it changed.

    Exits when two docs would rename to the same file. Returns the state the
    caller regenerates images-baseline.yaml from.
    """
    by_suffix = _check_no_collisions(paths, target)

    print(f"=== Bumping baseline for target {target} to {new_baseline} ===")
    review_notes, todo_stub_docs = _rebase_docs(paths, target, new_baseline, by_suffix)
    images_path = _bump_images_manifest_baseline(paths, target, new_baseline, review_notes)

    state = _load_rebase_state(paths, target, new_baseline)
    actual_changed_keys: set[str] = (
        compute_changed_components(state.target_deps, state.baseline_deps, state.target_values, state.baseline_values)
        if state.baseline_deps is not None
        else set()
    )

    upgrade_path = paths.doc_dir / doc_name(new_baseline, target, "upgrade")
    _fix_upgrade_doc(state, upgrade_path, actual_changed_keys)
    _fix_images_manifest_content(state, images_path, upgrade_path)
    values_deltas_path = paths.doc_dir / doc_name(new_baseline, target, "values-deltas")
    _fix_values_deltas(state, upgrade_path, values_deltas_path)

    if todo_stub_docs:
        print()
        print(f"removed stale TODO placeholder from {len(todo_stub_docs)} doc(s): {', '.join(todo_stub_docs)}")

    if review_notes:
        print()
        print("Review these lines by hand — old baseline text may remain in free-form prose:")
        for name, lines in review_notes:
            print(f"  {name}: line(s) {', '.join(map(str, lines))}")
    return state
