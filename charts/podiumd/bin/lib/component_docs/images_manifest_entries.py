"""Update/remove one component's entries and "# Changes:" item in
docs/images/images-<target>.yaml. Shared by update-component-version and
update-image-version."""

import re

from collections.abc import Iterable
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from lib.chart.chart_yaml import ChartDependency
from lib.chart.values_tree_primitives import replace_scalar_value
from lib.component_docs.changes_section import ComponentState
from lib.component_docs.changes_section import VersionChange
from lib.component_docs.images_manifest_changes_header import CHANGES_HEADER_RE
from lib.component_docs.images_manifest_changes_header import CHANGES_ITEM_RE
from lib.component_docs.images_manifest_changes_header import ensure_images_manifest_changes_header
from lib.component_docs.images_manifest_changes_header import find_changes_item
from lib.component_docs.images_manifest_changes_header import find_images_manifest_changes_header
from lib.component_docs.images_manifest_changes_header import find_images_manifest_changes_items
from lib.component_docs.images_manifest_changes_header import images_manifest_changes_count_word
from lib.component_docs.images_manifest_changes_header import images_manifest_changes_item_spans
from lib.component_docs.images_manifest_changes_header import images_manifest_order_key
from lib.component_docs.images_manifest_changes_header import insert_images_manifest_header_item
from lib.component_docs.images_manifest_changes_header import remove_changes_item
from lib.images_manifest import ManifestEntry
from lib.images_manifest import try_parse_images_manifest
from lib.upgradedoc.app_version_and_image_paths import resolve_entry_path
from lib.upgradedoc.grouped_comments_and_changes_block import find_grouped_preceding_comment_line
from lib.upgradedoc.images_manifest_ordering import delete_images_manifest_entry
from lib.upgradedoc.images_manifest_ordering import match_changes_item_display_name
from lib.upgradedoc.resolve_component_row import ResolutionContext
from lib.upgradedoc.resolve_component_row import resolve_component_row
from lib.upgradedoc.resolve_component_row import resolved_row_unchanged
from lib.upgradedoc.sorting_and_ordering import values_key_order
from lib.upgradedoc.string_and_parsing_basics import extract_source_version
from lib.upgradedoc.string_and_parsing_basics import match_located_line
from lib.upgradedoc.string_and_parsing_basics import normalize_version
from lib.upgradedoc.string_and_parsing_basics import text_names
from lib.upgradedoc.version_cells_and_key_changes import image_manifest_version_text
from lib.upgradedoc.version_cells_and_key_changes import replace_version_pair
from lib.yaml_types import YamlMapping


@dataclass
class ManifestUpdateTarget:
    """Which manifest file and component the update/remove functions operate on."""

    images_path: Path
    friendly: str
    values_key: str


@dataclass
class ImagePathUpdate:
    """Image paths with their repo and new tag, looked up per path in lockstep."""

    paths: list[str]
    repos: dict[str, str]
    new_tags: dict[str, str]


@dataclass
class ParsedManifest:
    """Manifest lines with entries and their line indices, derived from and kept in sync with `lines`."""

    lines: list[str]
    entries: list[ManifestEntry]
    entry_line_indices: list[int]


def values_tree_path_for(values_key: str, image_path: str):
    """find_image_tag_paths key for a dotted image path (e.g. "frontend.image") under values_key."""
    segments = image_path.split(".")
    return (values_key, *tuple(segments[:-1]))


def find_matching_images_entry(
    entries: list[ManifestEntry], entry_line_indices: list[int], target_path: tuple[str, ...]
) -> tuple[ManifestEntry, int, int] | tuple[None, None, None]:
    """(entry, line_idx, index) of the entry resolving to target_path, or (None, None, None)."""
    for index, (entry, line_idx) in enumerate(zip(entries, entry_line_indices, strict=True)):
        if resolve_entry_path(entry["name"], [target_path]) == target_path:
            return entry, line_idx, index
    return None, None, None


def _parsed_manifest(lines: list[str]):
    """Re-parse entries/line indices from `lines` (possibly edited by a header change)."""
    entries = try_parse_images_manifest("".join(lines)) or []
    entry_line_indices = [i for i, line in enumerate(lines) if re.match(r"^-\s*name:", line)]
    return ParsedManifest(lines, entries, entry_line_indices)


def _component_of(values_key: str, entry: ManifestEntry):
    return values_key if text_names(entry["name"], values_key) else None


def _same_group(values_key: str, entry_a: ManifestEntry, entry_b: ManifestEntry) -> bool:
    """Whether both entries share component and version, i.e. one shared comment block."""
    return (
        _component_of(values_key, entry_a) is not None
        and _component_of(values_key, entry_a) == _component_of(values_key, entry_b)
        and entry_a.get("version") == entry_b.get("version")
    )


def _rewrite_entry_scalars(lines: list[str], entry_line_idx: int, new_app_version: str, digest: str):
    """Overwrite version:/digest: lines in this entry's block; True if anything changed."""
    block_end = len(lines)
    for i in range(entry_line_idx + 1, len(lines)):
        if re.match(r"^-\s*name:", lines[i]) or not lines[i].strip():
            block_end = i
            break
    changed = False
    for i in range(entry_line_idx, block_end):
        m = re.match(r"^\s*(version|digest):", lines[i])
        if not m:
            continue
        new_value = new_app_version if m.group(1) == "version" else digest
        lines[i] = replace_scalar_value(lines[i], new_value)
        changed = True
    return changed


def update_images_manifest_entry(manifest: ParsedManifest, index: int, new_tag: str, values_key: str):
    """Update an entry's version/digest and its preceding comment's version pair.

    The comment may be shared by several entries of this component (see
    _same_group). Returns True if anything changed."""
    entry_line_idx = manifest.entry_line_indices[index]
    new_app_version, digest = new_tag.split("@", 1)
    changed = _rewrite_entry_scalars(manifest.lines, entry_line_idx, new_app_version, digest)

    comment_idx = find_grouped_preceding_comment_line(
        manifest.lines,
        manifest.entries,
        manifest.entry_line_indices,
        index,
        lambda entry_a, entry_b: _same_group(values_key, entry_a, entry_b),
    )
    if comment_idx is not None:
        current_source = extract_source_version(manifest.lines[comment_idx])
        if current_source:
            manifest.lines[comment_idx] = replace_version_pair(
                manifest.lines[comment_idx], current_source, new_app_version
            )
            changed = True
    return changed


def changes_header_item_text(friendly: str, change: VersionChange):
    """Changes-header item text; native components (new_chart "-") get no "(chart ...)" clause."""
    if change.new_chart == "-":
        return f"{friendly} {image_manifest_version_text(change.old_app, change.new_app)}."
    chart_changed = normalize_version(change.old_chart) != normalize_version(change.new_chart)
    chart_bit = f"{change.old_chart} -> {change.new_chart}" if chart_changed else f"{change.new_chart}, unchanged"
    return f"{friendly} {image_manifest_version_text(change.old_app, change.new_app)} (chart {chart_bit})."


@dataclass(frozen=True)
class ExpectedChangesItem:
    """A row's "# Changes:" item: "<name> <versions>" and, for a dependency, its "(chart ...)" clause."""

    core: str
    chart_clause: str | None
    chart_changed: bool

    def text(self, *, with_chart: bool) -> str:
        """The item text; the chart clause when asked for or when the chart version changed."""
        if self.chart_clause and (with_chart or self.chart_changed):
            return f"{self.core} {self.chart_clause}."
        return f"{self.core}."


_CHART_CLAUSE_RE = re.compile(r" (\(chart [^)]*\))\.$")


def expected_changes_items(
    row_names: Iterable[str], canonical_names: Mapping[str, tuple[str, ...]], resolution: ResolutionContext
) -> dict[str, ExpectedChangesItem]:
    """{row name: its expected "# Changes:" item} for each changed upgrade-doc table row.

    Resolved as the table row is (resolve_component_row), so the item can't
    contradict the row. Rows unchanged vs the baseline, or not fully
    resolvable, are left out.
    """
    expected: dict[str, ExpectedChangesItem] = {}
    for name in row_names:
        resolved = resolve_component_row(name, canonical_names, resolution)
        if resolved["kind"] == "unmatched" or resolved["target_app"] is None or resolved["baseline_app"] is None:
            continue
        if resolved["kind"] != "native" and resolved["baseline_resolved"] is not True:
            continue
        if resolved_row_unchanged(resolved):
            continue
        chart_clause = None
        chart_changed = False
        if resolved["kind"] == "dependency":
            if resolved["baseline_chart"] is None or resolved["target_chart"] is None:
                continue
            change = VersionChange(
                resolved["baseline_app"], resolved["target_app"], resolved["baseline_chart"], resolved["target_chart"]
            )
            m = _CHART_CLAUSE_RE.search(changes_header_item_text(name, change))
            chart_clause = m.group(1) if m else None
            chart_changed = normalize_version(resolved["baseline_chart"]) != normalize_version(resolved["target_chart"])
        core = f"{name} {image_manifest_version_text(resolved['baseline_app'], resolved['target_app'])}"
        expected[name] = ExpectedChangesItem(core, chart_clause, chart_changed)
    return expected


def stale_changes_items(lines: list[str], expected: Mapping[str, ExpectedChangesItem]) -> list[tuple[int, str, str]]:
    """(line index, current text, expected text) of each one-line "# Changes:" item that contradicts its row.

    An item belongs to the longest row name it names (match_changes_item_display_name),
    so a sidecar item "zac - solr ..." never belongs to row "zac". Its versions must
    match. The "(chart ...)" clause is required when the chart version
    changed; otherwise only checked when present, since update-image-version
    writes dependency items without it.
    """
    header_idx, _header_has_count = find_images_manifest_changes_header(lines)
    if header_idx is None:
        return []
    spans, _block_end = images_manifest_changes_item_spans(lines, header_idx)
    stale: list[tuple[int, str, str]] = []
    for start, end in spans:
        if end - start != 1:
            continue
        rest = match_located_line(CHANGES_ITEM_RE, lines[start]).group("rest").strip()
        name = match_changes_item_display_name(rest, expected)
        if name is None:
            continue
        wanted = expected[name].text(with_chart=_CHART_CLAUSE_RE.search(rest) is not None)
        if rest != wanted:
            stale.append((start, rest, wanted))
    return stale


def fix_stale_changes_items(lines: list[str], expected: Mapping[str, ExpectedChangesItem]) -> list[tuple[str, str]]:
    """Rewrite the items stale_changes_items reports, keeping their numbers; returns [(old, new), ...]."""
    fixed: list[tuple[str, str]] = []
    for idx, current, wanted in stale_changes_items(lines, expected):
        m = match_located_line(CHANGES_ITEM_RE, lines[idx])
        lines[idx] = f"#   {m.group('num')}. {wanted}\n"
        fixed.append((current, wanted))
    return fixed


def _update_changes_header_item(
    lines: list[str], target: ManifestUpdateTarget, change: VersionChange, state: ComponentState
):
    """Update this component's changes-header item, or insert it in values.yaml order.

    Returns "updated" or "added"."""
    _header_idx, _header_has_count, item_indices = find_images_manifest_changes_items(lines)
    match_idx = find_changes_item(lines, item_indices, target.friendly)
    item_text = changes_header_item_text(target.friendly, change)

    if match_idx is not None:
        m = match_located_line(CHANGES_ITEM_RE, lines[match_idx])
        lines[match_idx] = f"#   {m.group('num')}. {item_text}\n"
        return "updated"

    key_order = values_key_order(state.values)
    new_key = images_manifest_order_key(key_order, target.values_key, is_sidecar=" - " in target.friendly)
    insert_images_manifest_header_item(lines, state.deps, key_order, new_key, item_text)
    return "added"


def _apply_entry_updates(
    manifest: ParsedManifest, path_update: ImagePathUpdate, values_key: str
) -> tuple[list[str], list[tuple[str, str, str]]]:
    """Update existing entries for path_update.paths.

    Returns (entry_names_updated, missing_entries), missing_entries being
    [(image_path, repo, new_tag), ...] for paths without an entry."""
    entry_updates: list[str] = []
    missing_entries: list[tuple[str, str, str]] = []
    for path in path_update.paths:
        target_path = values_tree_path_for(values_key, path)
        entry, _entry_idx, index = find_matching_images_entry(
            manifest.entries, manifest.entry_line_indices, target_path
        )
        if entry is None or index is None:
            missing_entries.append((path, path_update.repos[path], path_update.new_tags[path]))
            continue
        if update_images_manifest_entry(manifest, index, path_update.new_tags[path], values_key):
            entry_updates.append(entry["name"])
    return entry_updates, missing_entries


def update_images_manifest(
    target: ManifestUpdateTarget,
    change: VersionChange,
    path_update: ImagePathUpdate,
    deps: list[ChartDependency],
    values: YamlMapping,
):
    """Update the "# <N> changes:" item and existing entries for this component.

    Returns (changes_action, entry_names_updated, missing_entries). Missing
    entries are not created here; the callers' closing fix-doc-consistency
    run adds them. A new header item is inserted in values.yaml order, same
    as fix-doc-consistency, so a later run doesn't reshuffle it."""
    original_text = target.images_path.read_text(encoding="utf-8")
    lines = original_text.splitlines(keepends=True)

    # insert_images_manifest_header_item is a no-op without a header, so a
    # header-less manifest would otherwise never get this component's item.
    ensure_images_manifest_changes_header(lines)
    header_idx, _header_has_count = find_images_manifest_changes_header(lines)

    changes_action = None
    if header_idx is not None:
        changes_action = _update_changes_header_item(lines, target, change, ComponentState(deps, values))

    manifest = _parsed_manifest(lines)
    entry_updates, missing_entries = _apply_entry_updates(manifest, path_update, target.values_key)

    new_text = "".join(lines)
    if new_text != original_text:
        target.images_path.write_text(new_text, encoding="utf-8")
    return changes_action, entry_updates, missing_entries


def _remove_changes_header_item(lines: list[str], friendly: str):
    """Delete this component's changes-header item, renumbering the rest and updating the count word.

    Returns "removed", or None if no item matched."""
    header_idx, header_has_count, item_indices = find_images_manifest_changes_items(lines)
    match_idx = find_changes_item(lines, item_indices, friendly)
    if match_idx is None:
        return None

    remaining = len(remove_changes_item(lines, item_indices, match_idx))
    if header_has_count and header_idx is not None:
        count_word, noun = images_manifest_changes_count_word(remaining)
        header_m = match_located_line(CHANGES_HEADER_RE, lines[header_idx])
        lines[header_idx] = f"{header_m.group('indent')}{count_word} {noun}:\n"
    # else: bare "# Changes:" header is left as-is.
    return "removed"


def _remove_entries(manifest: ParsedManifest, path_update: ImagePathUpdate, values_key: str) -> list[str]:
    """Delete every matching entry with its comment, last first to keep indices valid.

    Returns entry_names_removed."""
    found: list[tuple[int, str]] = []
    for path in path_update.paths:
        target_path = values_tree_path_for(values_key, path)
        entry, entry_idx, _index = find_matching_images_entry(
            manifest.entries, manifest.entry_line_indices, target_path
        )
        if entry is not None and entry_idx is not None:
            found.append((entry_idx, entry["name"]))
    for entry_idx, _name in sorted(set(found), reverse=True):
        delete_images_manifest_entry(manifest.lines, entry_idx)
    return [name for _idx, name in sorted(set(found))]


def remove_component_from_images_manifest(target: ManifestUpdateTarget, path_update: ImagePathUpdate):
    """Remove this component's header item and entries when a bump nets out to no change vs the baseline.

    A same-version re-pin with a new digest is re-added as "(digest changed)"
    by the following fix-doc-consistency run. path_update.repos/new_tags are
    unused. Returns (changes_action, entry_names_removed), changes_action
    "removed" or None."""
    original_text = target.images_path.read_text(encoding="utf-8")
    lines = original_text.splitlines(keepends=True)

    header_idx, _header_has_count = find_images_manifest_changes_header(lines)
    changes_action = _remove_changes_header_item(lines, target.friendly) if header_idx is not None else None

    manifest = _parsed_manifest(lines)
    entry_removals = _remove_entries(manifest, path_update, target.values_key)

    new_text = "".join(lines)
    if new_text != original_text:
        target.images_path.write_text(new_text, encoding="utf-8")
    return changes_action, entry_removals
