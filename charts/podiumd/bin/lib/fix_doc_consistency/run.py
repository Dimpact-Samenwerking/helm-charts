"""fix-doc-consistency's pipeline: rebase the upgrade docs of a target onto its baseline and repair their content.

fix_docs writes the docs under FixDocPaths. The script runs it on the real
docs; check_docs_consistency runs it on a copy and reports the difference.
The docs of a declared side path (release-baseline.yaml's side_paths) are a
second upgrade path to the same target: repaired against their own baseline,
never rebased, never stubbed, and the images manifest stays the main path's.
"""

import sys

from collections.abc import Collection
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from lib.component_docs.baseline_doc_stubs import IMAGES_STUB_TEMPLATE
from lib.component_docs.baseline_doc_stubs import STUB_TEMPLATES
from lib.component_docs.baseline_doc_stubs import existing_doc_baselines
from lib.component_docs.changes_section import strip_stale_upgrade_placeholders
from lib.component_docs.values_delta_sections import strip_stale_values_deltas_todo_stub
from lib.fix_doc_consistency.baseline_and_images_manifest_handling import extract_images_baseline
from lib.fix_doc_consistency.baseline_and_images_manifest_handling import fix_images_manifest_header_lines
from lib.fix_doc_consistency.baseline_and_images_manifest_handling import update_sibling_doc_refs
from lib.fix_doc_consistency.images_manifest_steps import fix_images_manifest_content
from lib.fix_doc_consistency.rebase_state import FixDocPaths
from lib.fix_doc_consistency.rebase_state import RebaseState
from lib.fix_doc_consistency.rebase_state import load_baseline_state
from lib.fix_doc_consistency.rebase_state import load_target_state
from lib.fix_doc_consistency.text_helpers_and_repo_rename import DocsBySuffix
from lib.fix_doc_consistency.text_helpers_and_repo_rename import collapse_multiple_blank_lines
from lib.fix_doc_consistency.text_helpers_and_repo_rename import find_collisions
from lib.fix_doc_consistency.text_helpers_and_repo_rename import join_and
from lib.fix_doc_consistency.text_helpers_and_repo_rename import remaining_mentions
from lib.fix_doc_consistency.text_helpers_and_repo_rename import update_component_versions_heading
from lib.fix_doc_consistency.text_helpers_and_repo_rename import update_title_line
from lib.fix_doc_consistency.upgrade_doc_steps import fix_upgrade_doc_content
from lib.fix_doc_consistency.upgrade_doc_steps import fix_values_deltas_content
from lib.upgradedoc.baseline_intro import fix_baseline_intro
from lib.upgradedoc.doc_names import STANDARD_SUFFIXES
from lib.upgradedoc.doc_names import doc_name
from lib.upgradedoc.doc_names import images_manifest_path
from lib.upgradedoc.images_manifest_list_diff import compute_changed_components

# {side path: {suffix: doc path}} of the side paths' docs.
type SideDocs = dict[str, dict[str, Path]]


def _check_no_collisions(paths: FixDocPaths, target: str, side_paths: Collection[str]) -> tuple[DocsBySuffix, SideDocs]:
    """(the existing docs to rebase, by suffix; the side paths' docs, {side: {suffix: path}}).

    Exits if two docs outside the side paths would rename to the same file.
    """
    by_suffix: DocsBySuffix = {}
    side_docs: SideDocs = {}
    for suffix, entries in existing_doc_baselines(paths.doc_dir, target).items():
        for baseline, path in entries:
            if baseline in side_paths:
                side_docs.setdefault(baseline, {})[suffix] = path
            else:
                by_suffix.setdefault(suffix, []).append((baseline, path))
    collisions = find_collisions(by_suffix)
    if not collisions:
        return by_suffix, side_docs
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
    # (rebased doc, the baseline it was rebased from); its leftover mentions are
    # looked up once every fix has written it, so the line numbers match the file.
    old_baselines: list[tuple[Path, str]]
    # upgrade_docs and the side paths: the baselines with docs of their own.
    declared_paths: tuple[str, ...] = ()

    def other_paths(self, baseline: str) -> set[str]:
        """The declared paths other than `baseline`: references to their docs are links, not stale."""
        return set(self.declared_paths) - {baseline}


def _fix_refs_and_stubs(
    text: str, suffix: str, target: str, new_baseline: str, acc: RebaseAccumulator
) -> tuple[str, bool, bool]:
    """(text, refs_changed, todo_stripped): sibling-doc references rebased and a stale TODO stub removed.

    References to the target's other declared upgrade paths stay.
    """
    text, refs_changed = update_sibling_doc_refs(text, target, new_baseline, acc.other_paths(new_baseline))
    todo_stripped = False
    if suffix == "upgrade":
        text, todo_stripped = strip_stale_upgrade_placeholders(text)
    elif suffix == "values-deltas":
        text, todo_stripped = strip_stale_values_deltas_todo_stub(text)
    return text, refs_changed, todo_stripped


@dataclass
class HeaderChanges:
    """Which baseline mentions _rebase_header rewrote."""

    title: bool
    heading: bool
    intro: bool

    @property
    def has_changes(self) -> bool:
        """Whether any of them was rewritten."""
        return self.title or self.heading or self.intro


def _rebase_header(text: str, suffix: str, target: str, new_baseline: str) -> tuple[str, HeaderChanges]:
    """The title line, "Component versions" heading and (upgrade doc only) intro pointed at new_baseline.

    Shared by a renamed doc and one already named after new_baseline, which
    can still carry another baseline in these lines.
    """
    text, title = update_title_line(text, target, new_baseline)
    text, heading = update_component_versions_heading(text, target, new_baseline)
    intro = False
    if suffix == "upgrade":
        text, intro = fix_baseline_intro(text, new_baseline)
    return text, HeaderChanges(title, heading, intro)


def _rebase_already_at_baseline(doc: DocRename, target: str, new_baseline: str, acc: RebaseAccumulator):
    """Fix stale header lines, sibling refs, TODO stubs and double blank lines in a doc already at new_baseline."""
    text, header = _rebase_header(doc.path.read_text(encoding="utf-8"), doc.suffix, target, new_baseline)
    text, refs_changed, todo_stripped = _fix_refs_and_stubs(text, doc.suffix, target, new_baseline, acc)
    collapsed_text = collapse_multiple_blank_lines(text)
    blank_lines_fixed = collapsed_text != text
    if not (header.has_changes or refs_changed or blank_lines_fixed or todo_stripped):
        print(f"  {doc.path.name}: already baseline {new_baseline} — unchanged")
        return
    doc.path.write_text(collapsed_text, encoding="utf-8")
    parts: list[str] = []
    if header.title:
        parts.append(f"title line -> {new_baseline}")
    if header.heading:
        parts.append(f"'Component versions' heading -> {new_baseline}")
    if header.intro:
        parts.append(f"intro baseline -> {new_baseline}")
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
    """Rename doc onto new_baseline and rewrite its title, heading, intro, refs and stubs."""
    new_name = doc_name(new_baseline, target, doc.suffix)
    new_path = paths.doc_dir / new_name
    text = doc.path.read_text(encoding="utf-8")

    text, header = _rebase_header(text, doc.suffix, target, new_baseline)
    text, refs_changed, todo_stripped = _fix_refs_and_stubs(text, doc.suffix, target, new_baseline, acc)

    if doc.path != new_path:
        paths.rename(doc.path, new_path)
    new_path.write_text(collapse_multiple_blank_lines(text), encoding="utf-8")

    print(f"  {doc.path.name} -> {new_name}")
    if header.title:
        print(f"    title line: -> {new_baseline}")
    if header.heading:
        print(f"    'Component versions' heading: -> {new_baseline}")
    if header.intro:
        print(f"    intro baseline: -> {new_baseline}")
    if refs_changed:
        print(f"    sibling doc references: -> {new_baseline}-to-{target}-*.md")
    if todo_stripped:
        print("    removed stale TODO placeholder")
        acc.todo_stub_docs.append(new_name)

    acc.old_baselines.append((new_path, doc.old_baseline))


def _rebase_docs(
    paths: FixDocPaths,
    target: str,
    new_baseline: str,
    by_suffix: DocsBySuffix,
    acc: RebaseAccumulator,
):
    """Rebase every doc onto new_baseline, stubbing missing ones; findings go into `acc`."""
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

        # _check_no_collisions leaves one doc per suffix.
        old_baseline, path = by_suffix[suffix][0]
        doc = DocRename(path, old_baseline, suffix)
        if old_baseline == new_baseline:
            _rebase_already_at_baseline(doc, target, new_baseline, acc)
            continue

        _rebase_doc_to_new_baseline(paths, doc, target, new_baseline, acc)


def _bump_images_manifest_baseline(paths: FixDocPaths, target: str, new_baseline: str, acc: RebaseAccumulator):
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
    text, refs_changed = update_sibling_doc_refs(text, target, new_baseline, acc.other_paths(new_baseline))
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
        acc.old_baselines.append((images_path, old_images_baseline))
    return images_path


def _print_review_notes(old_baselines: list[tuple[Path, str]]):
    """The lines of each rebased doc, as written, that still name its old baseline."""
    notes = [
        (path.name, lines)
        for path, old_baseline in old_baselines
        if path.is_file() and (lines := remaining_mentions(path.read_text(encoding="utf-8"), old_baseline))
    ]
    if notes:
        print()
        print("Review these lines by hand — old baseline text may remain in free-form prose:")
        for name, lines in notes:
            print(f"  {name}: line(s) {', '.join(map(str, lines))}")


def _load_rebase_state(paths: FixDocPaths, target: str, new_baseline: str):
    """RebaseState for the current target and new_baseline."""
    target_deps, target_values = load_target_state(paths)
    baseline_deps, baseline_values = load_baseline_state(paths, new_baseline)
    return RebaseState(paths, target, new_baseline, target_deps, target_values, baseline_deps, baseline_values)


def _fix_hop_content(state: RebaseState, images_path: Path | None):
    """Repair the upgrade doc, the images manifest (main path only: `images_path`) and the values-deltas doc."""
    actual_changed_keys: set[str] = (
        compute_changed_components(
            state.target_deps,
            state.baseline_deps,
            state.target_values,
            state.baseline_values,
            chart_dir=state.paths.chart_dir,
        )
        if state.baseline_deps is not None
        else set()
    )
    upgrade_path = state.paths.doc_dir / doc_name(state.new_baseline, state.target, "upgrade")
    fix_upgrade_doc_content(state, upgrade_path, actual_changed_keys)
    if images_path is not None:
        fix_images_manifest_content(state, images_path, upgrade_path)
    values_deltas_path = state.paths.doc_dir / doc_name(state.new_baseline, state.target, "values-deltas")
    fix_values_deltas_content(state, upgrade_path, values_deltas_path)


def _fix_side_path(paths: FixDocPaths, target: str, side: str, docs: dict[str, Path], acc: RebaseAccumulator):
    """Repair the existing docs of side path `side` against its own baseline; never renames or stubs them."""
    print()
    print(f"=== Side path {side} -> {target} ===")
    for suffix, path in sorted(docs.items()):
        _rebase_already_at_baseline(DocRename(path, side, suffix), target, side, acc)
    _fix_hop_content(_load_rebase_state(paths, target, side), None)


def fix_docs(paths: FixDocPaths, target: str, new_baseline: str, side_paths: Sequence[str] = ()) -> RebaseState:
    """Rebase the docs of `target` onto `new_baseline`, repair their content and that of the side paths' docs.

    Prints what it changed. Exits when two docs outside the side paths would
    rename to the same file. Returns the main path's state, which the caller
    regenerates images-baseline.yaml from.
    """
    side_paths = [side for side in dict.fromkeys(side_paths) if side != new_baseline]
    by_suffix, side_docs = _check_no_collisions(paths, target, side_paths)

    print(f"=== Bumping baseline for target {target} to {new_baseline} ===")
    acc = RebaseAccumulator(todo_stub_docs=[], old_baselines=[], declared_paths=(new_baseline, *side_paths))
    _rebase_docs(paths, target, new_baseline, by_suffix, acc)
    images_path = _bump_images_manifest_baseline(paths, target, new_baseline, acc)

    state = _load_rebase_state(paths, target, new_baseline)
    _fix_hop_content(state, images_path)
    for side in side_paths:
        if side in side_docs:
            _fix_side_path(paths, target, side, side_docs[side], acc)

    if acc.todo_stub_docs:
        print()
        print(f"removed stale TODO placeholder from {len(acc.todo_stub_docs)} doc(s): {', '.join(acc.todo_stub_docs)}")

    _print_review_notes(acc.old_baselines)
    return state
