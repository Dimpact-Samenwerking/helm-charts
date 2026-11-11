"""fix-doc-consistency's images-manifest fixes: adding missing entries and removing stale ones."""

from collections.abc import Collection
from dataclasses import dataclass
from dataclasses import field
from functools import cached_property
from pathlib import Path
from typing import NamedTuple

from lib.chart.chart_yaml import ChartDependency
from lib.chart.historical_baselines import baseline_lookup
from lib.chart.pull_and_subchart_resolution import resolved_digest_pin
from lib.chart.registered_paths import is_primary_image_path
from lib.chart.repo_and_path_resolution import full_repository_for_path
from lib.chart.values_tree_primitives import ValuesPath
from lib.chart.values_tree_primitives import version_of
from lib.component_docs.images_manifest_changes_header import covered_display_names
from lib.component_docs.images_manifest_changes_header import ensure_changes_header
from lib.component_docs.images_manifest_changes_header import find_changes_header
from lib.component_docs.images_manifest_changes_header import find_changes_item
from lib.component_docs.images_manifest_changes_header import find_changes_items
from lib.component_docs.images_manifest_changes_header import images_manifest_changes_block
from lib.component_docs.images_manifest_changes_header import insert_header_item
from lib.component_docs.images_manifest_changes_header import remove_changes_item
from lib.component_docs.images_manifest_changes_header import uncovered_manifest_entries
from lib.fix_doc_consistency.manifest_entries_core import BaselineRelease
from lib.fix_doc_consistency.manifest_entries_core import entry_baseline_version
from lib.image.repository_check import find_images_without_repository
from lib.images_manifest import ENTRY_NAME_RE
from lib.images_manifest import entry_line_indices
from lib.images_manifest import try_parse_images_manifest
from lib.settings import DigestPinningException
from lib.settings import digest_pinning_exceptions
from lib.upgradedoc.chart_image_index import ChartImageIndex
from lib.upgradedoc.chart_image_index import StateImageIndexes
from lib.upgradedoc.chart_image_index import entry_resolution_of
from lib.upgradedoc.grouped_comments import path_display_name
from lib.upgradedoc.images_manifest_list_diff import ManifestDiffContext
from lib.upgradedoc.images_manifest_list_diff import ManifestDiffInputs
from lib.upgradedoc.images_manifest_list_diff import find_images_manifest_list_diff
from lib.upgradedoc.images_manifest_ordering import EntryResolution
from lib.upgradedoc.images_manifest_ordering import delete_images_manifest_entry
from lib.upgradedoc.images_manifest_ordering import images_manifest_block_start
from lib.upgradedoc.sorting_and_ordering import values_key_order
from lib.upgradedoc.string_and_parsing_basics import extract_source_version
from lib.upgradedoc.string_and_parsing_basics import extract_target_version
from lib.upgradedoc.string_and_parsing_basics import normalize_version
from lib.upgradedoc.version_cells import image_manifest_version_text
from lib.yaml_types import YamlMapping


@dataclass
class MissingEntriesContext:
    """Inputs for adding missing / removing stale manifest entries.

    indexes: the caller's StateImageIndexes, built when None. Reuse one
    context for every pass of a run: its resolution is built once.
    """

    chart_dir: Path
    deps: list[ChartDependency]
    target_values: YamlMapping
    baseline_values: YamlMapping | None
    allow_pull: bool = False
    baseline_release: BaselineRelease = field(default_factory=BaselineRelease)
    indexes: StateImageIndexes | None = None

    @cached_property
    def resolution(self) -> "MissingEntriesResolution":
        """_entries_resolution of this context."""
        return _entries_resolution(self)

    @cached_property
    def entry_resolution(self) -> EntryResolution:
        """EntryResolution over the target paths and maps of `resolution`."""
        resolution = self.resolution
        return EntryResolution(
            self.deps, resolution.current_paths, resolution.repo.repo_map, resolution.canonical_names
        )


@dataclass
class BaselineResolution:
    """Baseline image paths and their repository groups."""

    baseline_paths: dict[ValuesPath, str]
    baseline_repo_groups: dict[str, list[ValuesPath]]


@dataclass
class RepoResolution:
    """Target repository groups, representative map and reverse map."""

    repo_groups: dict[str, list[ValuesPath]]
    repo_map: dict[str, ValuesPath]
    path_to_repo: dict[ValuesPath, str]


@dataclass
class MissingEntriesResolution:
    """Values computed once per run and shared by all passes; nested
    dataclasses keep it under pylint's max-instance-attributes."""

    current_paths: dict[ValuesPath, str]
    baseline: BaselineResolution
    repo: RepoResolution
    unresolvable_paths: set[ValuesPath]
    canonical_names: dict[str, ValuesPath]
    key_order: list[str]
    sibling_fields: dict[ValuesPath, DigestPinningException]


@dataclass
class AddedEntryFields:
    """Fields of a new entry, used for both its block and header item."""

    name: str
    repo: str
    full_repo_url: str | None
    pinned_tag: str


def _changes_header_text(lines: list[str]):
    """Text of the "# Changes:" header block (with wrapped items), or ""
    if there is none."""
    header_idx, _has_count = find_changes_header(lines)
    if header_idx is None:
        return ""
    block_end = images_manifest_changes_block(lines, header_idx)[1]
    return "".join(lines[header_idx:block_end])


def _manifest_list_diff(
    text: str, context: MissingEntriesContext, resolution: MissingEntriesResolution
) -> tuple[list[ValuesPath], list[str], list[str]]:
    """find_images_manifest_list_diff's result for `text`: the same diff
    verify-podiumd reports."""
    entries = try_parse_images_manifest(text) or []
    return find_images_manifest_list_diff(
        ManifestDiffInputs(
            entries,
            resolution.current_paths,
            resolution.baseline.baseline_paths,
            resolution.repo.repo_map,
            resolution.repo.repo_groups,
            resolution.unresolvable_paths,
            context=ManifestDiffContext(
                chart_dir=context.chart_dir,
                deps=context.deps,
                upgrade_docs_baseline=context.baseline_release.name,
                values=context.target_values,
                baseline_values=context.baseline_values,
            ),
        )
    )


def _entries_resolution(context: MissingEntriesContext) -> MissingEntriesResolution:
    """Shared per-run resolution for adding and removing entries."""
    indexes = context.indexes or StateImageIndexes.build(
        context.chart_dir, context.deps, context.target_values, context.baseline_values
    )
    target, baseline = indexes.target, indexes.baseline_values
    path_to_repo = {path: repo for repo, group_paths in target.repo_groups.items() for path in group_paths}
    return MissingEntriesResolution(
        target.paths,
        BaselineResolution(baseline.paths, baseline.repo_groups),
        RepoResolution(target.repo_groups, target.repo_map, path_to_repo),
        set(find_images_without_repository(context.chart_dir)),
        target.canonical_names,
        values_key_order(context.target_values),
        digest_pinning_exceptions(context.chart_dir),
    )


def _entry_fields_for_missing_path(
    path: tuple[str, ...], context: MissingEntriesContext, resolution: MissingEntriesResolution
) -> tuple[str, AddedEntryFields | None]:
    """(name, fields) for `path`; fields is None when no repository or
    digest-pinned tag resolves (name is still returned for reporting)."""
    repo = resolution.repo.path_to_repo.get(path)
    # repo is host-stripped (right for "name:"); "url:" needs the real host.
    full_repo_url = (
        full_repository_for_path(
            context.chart_dir, context.deps, context.target_values, path, allow_pull=context.allow_pull
        )
        or repo
    )
    current_tag = resolution.current_paths[path]
    name = path_display_name(path, context.deps, resolution.canonical_names)
    pinned_tag = resolved_digest_pin(context.target_values, path, current_tag, resolution.sibling_fields)
    if repo is None or pinned_tag is None:
        return name, None
    return name, AddedEntryFields(name, repo, full_repo_url, pinned_tag)


def _old_version_and_digest(
    path: tuple[str, ...],
    new_version: str,
    pinned_tag: str,
    context: MissingEntriesContext,
    resolution: MissingEntriesResolution,
) -> tuple[str | None, bool]:
    """(old_version, digest_only_change) for a new entry's comment: from the
    baseline path (flagging a same-version re-pin so it doesn't render
    "<v> -> <v>"), else entry_baseline_version."""
    baseline_tag = resolution.baseline.baseline_paths.get(path)
    if baseline_tag:
        old_version = version_of(baseline_tag)
        digest_only_change = False
        if normalize_version(old_version) == normalize_version(new_version):
            baseline_pinned_tag = resolved_digest_pin(
                context.baseline_values, path, baseline_tag, resolution.sibling_fields
            )
            if baseline_pinned_tag:
                digest_only_change = pinned_tag.split("@", 1)[1] != baseline_pinned_tag.split("@", 1)[1]
        return old_version, digest_only_change

    old_version = entry_baseline_version(
        baseline_lookup(
            context.chart_dir, context.deps, context.target_values, context.baseline_values, resolution.baseline
        ),
        path,
        context.baseline_release,
    )
    return old_version, False


def _manifest_lines_for_insert(text: str):
    """Lines with a trailing newline ensured and the stub's bare "[]" (see
    IMAGES_STUB_TEMPLATE) plus trailing blanks removed. Leaving "[]" before
    the first entry yields YAML later runs parse as empty, re-adding every
    entry. A manifest with "[]" has no real entries yet, so trimming is
    safe."""
    lines = text.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] = f"{lines[-1]}\n"
    if any(line.strip() == "[]" for line in lines):
        lines = [line for line in lines if line.strip() != "[]"]
        while lines and not lines[-1].strip():
            lines.pop()
    return lines


def _append_entry_block(lines: list[str], block_lines: list[str]) -> None:
    """Append a new entry block; sort_images_manifest_entries puts it in place afterwards."""
    lines.append("\n")
    lines.extend(block_lines)


def _insert_added_entry(
    text: str,
    path: tuple[str, ...],
    context: MissingEntriesContext,
    resolution: MissingEntriesResolution,
    fields: AddedEntryFields,
):
    """Insert the new entry block, plus a header item unless the header
    already names it (e.g. a lockstep sibling). Returns the text."""
    new_version, digest = fields.pinned_tag.split("@", 1)
    old_version, digest_only_change = _old_version_and_digest(path, new_version, fields.pinned_tag, context, resolution)
    version_text = image_manifest_version_text(old_version, new_version, digest_only_change=digest_only_change)
    version_text = f"{fields.name} {version_text}"

    lines = _manifest_lines_for_insert(text)
    ensure_changes_header(lines)
    if fields.name not in covered_display_names(lines, [fields.name]):
        insert_header_item(lines, f"{version_text}.")

    header_prefix = "# " if is_primary_image_path(path, context.deps, context.chart_dir) else "#   sidecar: "
    block_lines = [
        f"{header_prefix}{version_text}\n",
        f"- name: {fields.repo}\n",
        f"  url: {fields.full_repo_url}\n",
        f'  version: "{new_version}"\n',
        f'  digest: "{digest}"\n',
    ]
    _append_entry_block(lines, block_lines)
    return "".join(lines)


def _backfilled_header_item(lines: list[str], context: MissingEntriesContext) -> tuple[str, str] | None:
    """(entry_name, header item) for the first uncovered_manifest_entries entry whose comment has its versions."""
    for idx, entry_name in uncovered_manifest_entries(lines, context.entry_resolution):
        comment_text = "".join(lines[images_manifest_block_start(lines, idx) : idx])
        entry_new = extract_target_version(comment_text)
        if entry_new is not None:
            entry_old = extract_source_version(comment_text) or entry_new
            return entry_name, f"{entry_name} {entry_old} -> {entry_new}."
    return None


def _backfill_header_items(text: str, context: MissingEntriesContext) -> tuple[str, list[str]]:
    """Add a header item for each entry that has a block but no item,
    reading old/new versions from its existing comment. Returns
    (text, backfilled_names)."""
    backfilled_names: list[str] = []
    while True:
        lines = text.splitlines(keepends=True)
        ensure_changes_header(lines)
        header_text = _changes_header_text(lines)
        if not header_text:
            break
        text = "".join(lines)

        backfill = _backfilled_header_item(lines, context)
        if backfill is None:
            break

        entry_name, header_item = backfill
        insert_header_item(lines, header_item)
        text = "".join(lines)
        backfilled_names.append(entry_name)
    return text, backfilled_names


class MissingEntriesResult(NamedTuple):
    """add_missing_manifest_entries's result."""

    text: str
    added_names: list[str]
    skipped_names: list[str]
    backfilled_names: list[str]


def add_missing_manifest_entries(text: str, context: MissingEntriesContext) -> MissingEntriesResult:
    """Add an entry, its "# <name> <old> -> <new>" comment and a "# Changes:"
    header item for every missing path find_images_manifest_list_diff
    reports, then backfill header items (_backfill_header_items).

    Inserted in values.yaml component order; unresolvable existing items
    sort last without moving. "name:" is the stripped repository, not the
    curated ACR mirror slug (no mechanical formula; a human corrects it).
    version/digest come from the pinned tag in target_values; context.allow_pull
    lets the "url:" repository come from a pulled chart when it isn't vendored.
    Paths without a digest or repository are reported as skipped, never
    written incomplete.

    One path at a time, re-parsing after each insert, so shifted line
    indices need no bookkeeping. Global image paths take part directly and
    represent their repository group, so a shared image gets one entry."""
    resolution = context.resolution
    missing_paths, _stale_entry_names, _unmatched_entry_names = _manifest_list_diff(text, context, resolution)

    added_names: list[str] = []
    skipped_names: list[str] = []
    for path in missing_paths:
        name, fields = _entry_fields_for_missing_path(path, context, resolution)
        if fields is None:
            skipped_names.append(name)
            continue
        text = _insert_added_entry(text, path, context, resolution, fields)
        added_names.append(name)

    text, backfilled_names = _backfill_header_items(text, context)
    return MissingEntriesResult(text, added_names, skipped_names, backfilled_names)


def _remove_entry(
    lines: list[str],
    entry_name: str,
    display_name: str | None,
    context: MissingEntriesContext,
):
    """Delete the entry and its comment, and the "# Changes:" item naming
    display_name unless another entry has the same display name (lockstep component)."""
    entry_line = next(
        (
            index
            for index in entry_line_indices(lines)
            if (name_match := ENTRY_NAME_RE.match(lines[index])) and name_match.group(1) == entry_name
        ),
        None,
    )
    if entry_line is None:
        return
    delete_images_manifest_entry(lines, entry_line)
    if display_name is None:
        return
    remaining_display_names = {
        resolved[1]
        for entry in try_parse_images_manifest("".join(lines)) or []
        if (resolved := context.entry_resolution.entry_display_name(entry["name"]))
    }
    if display_name in remaining_display_names:
        return
    _header_idx, _header_has_count, item_indices = find_changes_items(lines)
    match_idx = find_changes_item(lines, item_indices, display_name)
    if match_idx is not None:
        remove_changes_item(lines, item_indices, match_idx)


def remove_stale_entries(text: str, context: MissingEntriesContext) -> tuple[str, list[str]]:
    """Delete every entry find_images_manifest_list_diff reports as stale
    (version and digest equal upgrade_docs_baseline), with its comment and
    "# Changes:" item; a later pass renumbers the count word. Entries with
    an unresolvable repository are kept for a human. Returns
    (new_text, removed_names)."""
    resolution = context.resolution
    _missing_paths, stale_entry_names, _unmatched_entry_names = _manifest_list_diff(text, context, resolution)
    entries = context.entry_resolution
    lines = text.splitlines(keepends=True)
    removable_names: list[str] = []
    for entry_name in stale_entry_names:
        resolved = entries.entry_display_name(entry_name)
        if resolved is not None and resolved[0] in resolution.unresolvable_paths:
            continue
        removable_names.append(entry_name)
        _remove_entry(lines, entry_name, None if resolved is None else resolved[1], context)
    return "".join(lines), removable_names


def remove_removed_entries(
    text: str, context: MissingEntriesContext, baseline: ChartImageIndex, removed_paths: Collection[ValuesPath]
) -> tuple[str, list[str]]:
    """Delete every entry whose image the target no longer has, with its comment and "# Changes:" item.

    An earlier bump in the cycle may have added it before its component or
    image was removed. Entries resolve against the baseline, where the image
    still is, and the item is named the way it was written there
    (path_display_name). removed_paths: removed_image_paths. Returns
    (new_text, removed entry names).
    """
    resolution = context.resolution
    _missing_paths, _stale_entry_names, unmatched_entry_names = _manifest_list_diff(text, context, resolution)
    lines = text.splitlines(keepends=True)
    baseline_entries = entry_resolution_of(baseline)
    removed_names: list[str] = []
    for entry_name in unmatched_entry_names:
        resolved = baseline_entries.entry_display_name(entry_name)
        if resolved is not None and resolved[0] in removed_paths:
            _remove_entry(lines, entry_name, resolved[1], context)
            removed_names.append(entry_name)
    return "".join(lines), removed_names
