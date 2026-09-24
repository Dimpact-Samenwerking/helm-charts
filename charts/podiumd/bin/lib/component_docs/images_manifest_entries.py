"""Update/remove a single component's own entries (and "# Changes:" header
item) in docs/images/images-<target>.yaml — the manifest-entry counterpart
to lib.component_docs.changes_section's table row / "## Changes" section.
Shared by update-component-version and update-image-version."""

import re

from dataclasses import dataclass
from pathlib import Path

import yaml

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
from lib.component_docs.images_manifest_changes_header import images_manifest_order_key
from lib.component_docs.images_manifest_changes_header import insert_images_manifest_header_item
from lib.component_docs.images_manifest_changes_header import remove_changes_item
from lib.upgradedoc.app_version_and_image_paths import resolve_entry_path
from lib.upgradedoc.grouped_comments_and_changes_block import find_grouped_preceding_comment_line
from lib.upgradedoc.sorting_and_ordering import values_key_order
from lib.upgradedoc.string_and_parsing_basics import extract_source_version
from lib.upgradedoc.string_and_parsing_basics import match_located_line
from lib.upgradedoc.string_and_parsing_basics import normalize_version
from lib.upgradedoc.string_and_parsing_basics import text_names
from lib.upgradedoc.version_cells_and_key_changes import image_manifest_version_text
from lib.upgradedoc.version_cells_and_key_changes import replace_version_pair


@dataclass
class ManifestUpdateTarget:
    """images_path/friendly/values_key -- which manifest file, and which
    component's own entries within it, update_images_manifest/remove_
    component_from_images_manifest operate on."""

    images_path: Path
    friendly: str
    values_key: str


@dataclass
class ImagePathUpdate:
    """paths/repos/new_tags, keyed together by image path -- update_images_
    manifest/remove_component_from_images_manifest both walk `paths` and
    look up each one's own repo/new-tag in lockstep (a missing manifest
    entry is reported as (path, repos[path], new_tags[path]), see update_
    images_manifest's own docstring)."""

    paths: list
    repos: dict
    new_tags: dict


@dataclass
class ParsedManifest:
    """lines/entries/entry_line_indices, kept in lockstep -- `entries`
    (yaml.safe_load'd) and `entry_line_indices` (parallel, one YAML-doc
    line index per entry) are both derived from `lines` and only ever
    meaningful read together; update_images_manifest_entry/find_matching_
    images_entry both need all three."""

    lines: list
    entries: list
    entry_line_indices: list


def values_tree_path_for(values_key: str, image_path: str):
    """The find_image_tag_paths key for a component_image_paths()-style
    dotted path (e.g. "frontend.image") under this component's values_key."""
    segments = image_path.split(".")
    return (values_key, *tuple(segments[:-1]))


def find_matching_images_entry(entries: list, entry_line_indices: list, target_path: tuple[str, ...]):
    """(entry, line_idx, index) for the parsed manifest entry whose own
    resolve_entry_path(entry["name"], ...) equals `target_path` (see
    values_tree_path_for), or (None, None, None) if this component has no
    existing entry for that image path yet — used by both update_images_
    manifest and remove_component_from_images_manifest to locate an
    entry's own YAML lines (entry_line_indices, parallel to `entries`) for
    in-place editing."""
    for index, (entry, line_idx) in enumerate(zip(entries, entry_line_indices, strict=True)):
        if resolve_entry_path(entry["name"], [target_path]) == target_path:
            return entry, line_idx, index
    return None, None, None


def _parsed_manifest(lines: list[str]):
    """entries/entry_line_indices parsed fresh from `lines` (already
    possibly mutated by a changes-header edit) — bundled as a
    ParsedManifest since update_images_manifest_entry/find_matching_
    images_entry both need all three (lines/entries/entry_line_indices)
    kept in lockstep."""
    entries = yaml.safe_load("".join(lines)) or []
    if not isinstance(entries, list):
        entries = []
    entry_line_indices = [i for i, line in enumerate(lines) if re.match(r"^-\s*name:", line)]
    return ParsedManifest(lines, entries, entry_line_indices)


def _component_of(values_key: str, entry: dict):
    return values_key if text_names(entry["name"], values_key) else None


def _same_group(values_key: str, entry_a: dict, entry_b: dict) -> bool:
    """Whether `entry_a`/`entry_b` share the same top-level component AND
    version — find_grouped_preceding_comment_line's own "same group"
    predicate, so a shared comment block (e.g. zgw-office-addin's frontend
    + backend, listed under one comment) is found for either entry, not
    just the line directly above it."""
    return (
        _component_of(values_key, entry_a) is not None
        and _component_of(values_key, entry_a) == _component_of(values_key, entry_b)
        and entry_a.get("version") == entry_b.get("version")
    )


def _rewrite_entry_scalars(lines: list[str], entry_line_idx: int, new_app_version: str, digest: str):
    """Overwrite the version:/digest: scalar lines within this entry's own
    block (up to the next "- name:" line or a blank line) in place.
    Returns True if anything actually changed."""
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
    """Update an existing entry's version/digest fields and its preceding
    comment's version pair in place. The comment may be shared across
    several of this component's entries (e.g. zgw-office-addin's frontend +
    backend, listed as one block under one comment) — found via the same
    top-level-component grouping as find_grouped_preceding_comment_line,
    not just the line directly above this entry. `manifest` is a
    ParsedManifest. Returns True if anything changed."""
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


def _changes_header_item_text(friendly: str, change: VersionChange):
    """The rendered "<friendly> <app transition> (chart <chart bit>)."
    changes-header list-item text for `change` (a VersionChange) — a
    native_components component (see lib.chart.native_components,
    `change.new_chart == "-"`) has no chart to verify against at all, so
    it gets no "(chart ...)" clause rather than a misleading one."""
    if change.new_chart == "-":
        return f"{friendly} {image_manifest_version_text(change.old_app, change.new_app)}."
    chart_changed = normalize_version(change.old_chart) != normalize_version(change.new_chart)
    chart_bit = f"{change.old_chart} -> {change.new_chart}" if chart_changed else f"{change.new_chart}, unchanged"
    return f"{friendly} {image_manifest_version_text(change.old_app, change.new_app)} (chart {chart_bit})."


def _update_changes_header_item(
    lines: list[str], target: ManifestUpdateTarget, change: VersionChange, state: ComponentState
):
    """Update this component's own existing changes-header list item in
    place, or insert a brand-new one at its own values.yaml-order slot
    (see update_images_manifest's own docstring for why the position
    matters) when it doesn't have one yet. `target` is a
    ManifestUpdateTarget (only its own `friendly`/`values_key` are used
    here), `state` a ComponentState (deps/values). Returns "updated" or
    "added"."""
    _header_idx, _header_has_count, item_indices = find_images_manifest_changes_items(lines)
    match_idx = find_changes_item(lines, item_indices, target.friendly)
    item_text = _changes_header_item_text(target.friendly, change)

    if match_idx is not None:
        m = match_located_line(CHANGES_ITEM_RE, lines[match_idx])
        lines[match_idx] = f"#   {m.group('num')}. {item_text}\n"
        return "updated"

    key_order = values_key_order(state.values)
    new_key = images_manifest_order_key(key_order, target.values_key, is_sidecar=" - " in target.friendly)
    insert_images_manifest_header_item(lines, state.deps, key_order, new_key, item_text)
    return "added"


def _apply_entry_updates(manifest: ParsedManifest, path_update: ImagePathUpdate, values_key: str):
    """Update every existing manifest entry for `path_update.paths`,
    returning (entry_names_updated, missing_entries) — missing_entries is
    [(image_path, repo, new_tag), ...] for a component_image_paths() path
    with no matching manifest entry yet (see update_images_manifest's own
    docstring for why nothing here invents one)."""
    entry_updates, missing_entries = [], []
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
    target: ManifestUpdateTarget, change: VersionChange, path_update: ImagePathUpdate, deps: list, values: dict
):
    """Update the "# <N> changes:" header list and any existing entries'
    version/digest/comment for this component. `target` is a
    ManifestUpdateTarget, `change` a VersionChange, `path_update` an
    ImagePathUpdate. Returns (changes_action, entry_names_updated,
    missing_entries) where missing_entries is [(image_path, repo,
    new_tag), ...] for components with no existing entry — never invented
    here. "name:" is mechanically derivable now (strip_registry(repo), see
    docs/images/acr-mirror-naming.md) but this function doesn't compute it
    — a full manifest entry still needs a human-authored comment/heading,
    so callers print a placeholder and leave the whole entry for manual
    review rather than a script writing part of it and a human the rest.

    deps/values position a brand-new header item at its own values.yaml-
    order slot (via insert_images_manifest_header_item/images_manifest_
    order_key — the SAME convention fix-doc-consistency's own add_
    missing_images_manifest_entries already uses) instead of always
    appending at the very end — real bug this fixes: update-image-
    version/update-component-version writing a new item that then sat
    out of order until a LATER fix-doc-consistency run reshuffled it,
    even though nothing else about the manifest was actually wrong.
    Updating an EXISTING item never needs them for anything — the far
    more common path here — so they're only ever read on a genuinely new
    item."""
    original_text = target.images_path.read_text(encoding="utf-8")
    lines = original_text.splitlines(keepends=True)

    # A file that has lost its "# Changes:" header (or never had one) —
    # see ensure_images_manifest_changes_header's own docstring for the
    # real bug this fixes: insert_images_manifest_header_item is a
    # documented no-op with no header to insert into, so without this,
    # a component bumped via update-component-version/update-image-
    # version into a header-less manifest would silently never get a
    # "# Changes:" list item, exactly the fix-doc-consistency-side gap
    # this same fix already closed for add_missing_images_manifest_
    # entries — this is the same gap in THESE scripts' own write path.
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
    """Delete this component's own "#   <N>. ..." changes-header list
    item (renumbering the rest) and update the header's own count word,
    when it has one — mirrors _update_changes_header_item's own item-match
    logic (shared via find_images_manifest_changes_items/find_changes_item)
    but for removal instead of update/insert. Returns "removed" or None
    (no matching item found)."""
    header_idx, header_has_count, item_indices = find_images_manifest_changes_items(lines)
    match_idx = find_changes_item(lines, item_indices, friendly)
    if match_idx is None:
        return None

    remaining = len(remove_changes_item(lines, item_indices, match_idx))
    if header_has_count and header_idx is not None:
        count_word, noun = images_manifest_changes_count_word(remaining)
        header_m = match_located_line(CHANGES_HEADER_RE, lines[header_idx])
        lines[header_idx] = f"{header_m.group('indent')}{count_word} {noun}:\n"
    # else: bare "# Changes:" header — left as-is, same convention
    # update_images_manifest's own insertion path follows.
    return "removed"


def _remove_entry_updates(manifest: ParsedManifest, path_update: ImagePathUpdate, values_key: str):
    """Rewrite every touched entry's final version/digest (still correct
    even with no change left to document, see remove_component_from_
    images_manifest's own docstring) and delete its own preceding source
    comment line, when it has one. Returns entry_names_updated."""
    entry_updates, comment_lines_to_remove = [], []
    for path in path_update.paths:
        target_path = values_tree_path_for(values_key, path)
        entry, entry_idx, index = find_matching_images_entry(manifest.entries, manifest.entry_line_indices, target_path)
        if entry is None or index is None or entry_idx is None:
            continue
        new_app_version, digest = path_update.new_tags[path].split("@", 1)
        _rewrite_entry_scalars(manifest.lines, entry_idx, new_app_version, digest)

        comment_idx = find_grouped_preceding_comment_line(
            manifest.lines,
            manifest.entries,
            manifest.entry_line_indices,
            index,
            lambda entry_a, entry_b: _same_group(values_key, entry_a, entry_b),
        )
        if comment_idx is not None and extract_source_version(manifest.lines[comment_idx]):
            comment_lines_to_remove.append(comment_idx)
        entry_updates.append(entry["name"])

    for idx in sorted(set(comment_lines_to_remove), reverse=True):
        del manifest.lines[idx]
    return entry_updates


def remove_component_from_images_manifest(target: ManifestUpdateTarget, path_update: ImagePathUpdate):
    """Counterpart to update_images_manifest for a bump that nets out to no
    change from upgrade_docs_baseline at all (see lib.upgradedoc.compute_changed_
    components): still writes each touched entry's final version/digest —
    the manifest's job is to list the correct final state for every image
    regardless of change-tracking — but removes the "changes:" list item
    and each entry's own preceding source comment instead of updating
    them, since there is no longer anything to document. `target` is a
    ManifestUpdateTarget, `path_update` an ImagePathUpdate (its own
    `repos` field is unused here — kept only for symmetry with
    update_images_manifest's own ImagePathUpdate). Returns (changes_action,
    entry_names_updated) — changes_action is "removed" or None (no
    matching list item found)."""
    original_text = target.images_path.read_text(encoding="utf-8")
    lines = original_text.splitlines(keepends=True)

    header_idx, _header_has_count = find_images_manifest_changes_header(lines)
    changes_action = _remove_changes_header_item(lines, target.friendly) if header_idx is not None else None

    manifest = _parsed_manifest(lines)
    entry_updates = _remove_entry_updates(manifest, path_update, target.values_key)

    new_text = "".join(lines)
    if new_text != original_text:
        target.images_path.write_text(new_text, encoding="utf-8")
    return changes_action, entry_updates
