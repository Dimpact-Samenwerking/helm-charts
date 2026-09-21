"""Update/remove a single component's own entries (and "# Changes:" header
item) in docs/images/images-<target>.yaml — the manifest-entry counterpart
to lib.component_docs.changes_section's table row / "## Changes" section.
Shared by update-component-version and update-image-version."""

import re

import yaml

from lib.chart.values_tree_primitives import replace_scalar_value
from lib.component_docs.images_manifest_changes_header import (
    CHANGES_HEADER_RE,
    CHANGES_ITEM_RE,
    NUMBER_WORDS,
    ensure_images_manifest_changes_header,
    find_images_manifest_changes_header,
    images_manifest_order_key,
    insert_images_manifest_header_item,
)
from lib.upgradedoc.app_version_and_image_paths import resolve_entry_path
from lib.upgradedoc.grouped_comments_and_changes_block import find_grouped_preceding_comment_line
from lib.upgradedoc.sorting_and_ordering import values_key_order
from lib.upgradedoc.string_and_parsing_basics import extract_source_version, normalize_name, normalize_version
from lib.upgradedoc.version_cells_and_key_changes import image_manifest_version_text, replace_version_pair


def values_tree_path_for(values_key, image_path):
    """The find_image_tag_paths key for a component_image_paths()-style
    dotted path (e.g. "frontend.image") under this component's values_key."""
    segments = image_path.split(".")
    return (values_key,) + tuple(segments[:-1])


def find_matching_images_entry(entries, entry_line_indices, target_path):
    for index, (entry, line_idx) in enumerate(zip(entries, entry_line_indices, strict=True)):
        if resolve_entry_path(entry["name"], [target_path]) == target_path:
            return entry, line_idx, index
    return None, None, None


def update_images_manifest_entry(lines, entries, entry_line_indices, index, new_tag, values_key):
    """Update an existing entry's version/digest fields and its preceding
    comment's version pair in place. The comment may be shared across
    several of this component's entries (e.g. zgw-office-addin's frontend +
    backend, listed as one block under one comment) — found via the same
    top-level-component grouping as find_grouped_preceding_comment_line,
    not just the line directly above this entry. Returns True if anything
    changed."""
    entry_line_idx = entry_line_indices[index]
    new_app_version, digest = new_tag.split("@", 1)
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

    def component_of(entry):
        return values_key if normalize_name(values_key) in normalize_name(entry["name"]) else None

    def same_group(entry_a, entry_b):
        return (
            component_of(entry_a) is not None
            and component_of(entry_a) == component_of(entry_b)
            and entry_a.get("version") == entry_b.get("version")
        )

    comment_idx = find_grouped_preceding_comment_line(lines, entries, entry_line_indices, index, same_group)
    if comment_idx is not None:
        current_source = extract_source_version(lines[comment_idx])
        if current_source:
            lines[comment_idx] = replace_version_pair(lines[comment_idx], current_source, new_app_version)
            changed = True
    return changed


def update_images_manifest(
    images_path,
    friendly,
    values_key,
    old_app,
    new_app,
    old_chart,
    new_chart,
    paths_to_update,
    repos,
    new_tags_by_path,
    deps,
    values,
):
    """Update the "# <N> changes:" header list and any existing entries'
    version/digest/comment for this component. Returns (changes_action,
    entry_names_updated, missing_entries) where missing_entries is
    [(image_path, repo, new_tag), ...] for components with no existing
    entry — never invented here. "name:" is mechanically derivable now
    (strip_registry(repo), see docs/images/acr-mirror-naming.md) but this
    function doesn't compute it — a full manifest entry still needs a
    human-authored comment/heading, so callers print a placeholder and
    leave the whole entry for manual review rather than a script writing
    part of it and a human the rest.

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
    original_text = images_path.read_text(encoding="utf-8")
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
        item_indices = []
        for i in range(header_idx + 1, len(lines)):
            if lines[i].rstrip("\n") == "#" or not lines[i].startswith("#"):
                break
            if re.match(r"^#\s*\d+\.", lines[i]):
                item_indices.append(i)

        norm_friendly = normalize_name(friendly)
        match_idx = None
        for idx in item_indices:
            m = CHANGES_ITEM_RE.match(lines[idx])
            if m and norm_friendly in normalize_name(m.group("rest")):
                match_idx = idx
                break

        if new_chart == "-":
            # native_components component (see lib.chart.native_components)
            # — no chart at all, so no "(chart ...)" clause to render.
            item_text = f"{friendly} {image_manifest_version_text(old_app, new_app)}."
        else:
            chart_changed = normalize_version(old_chart) != normalize_version(new_chart)
            chart_bit = f"{old_chart} -> {new_chart}" if chart_changed else f"{new_chart}, unchanged"
            item_text = f"{friendly} {image_manifest_version_text(old_app, new_app)} (chart {chart_bit})."

        if match_idx is not None:
            m = CHANGES_ITEM_RE.match(lines[match_idx])
            lines[match_idx] = f"#   {m.group('num')}. {item_text}\n"
            changes_action = "updated"
        else:
            key_order = values_key_order(values)
            new_key = images_manifest_order_key(key_order, values_key, " - " in friendly)
            insert_images_manifest_header_item(lines, deps, key_order, new_key, item_text)
            changes_action = "added"

    entries = yaml.safe_load("".join(lines)) or []
    if not isinstance(entries, list):
        entries = []
    entry_line_indices = [i for i, line in enumerate(lines) if re.match(r"^-\s*name:", line)]

    entry_updates, missing_entries = [], []
    for path in paths_to_update:
        target_path = values_tree_path_for(values_key, path)
        entry, entry_idx, index = find_matching_images_entry(entries, entry_line_indices, target_path)
        if entry is None:
            missing_entries.append((path, repos[path], new_tags_by_path[path]))
            continue
        if update_images_manifest_entry(lines, entries, entry_line_indices, index, new_tags_by_path[path], values_key):
            entry_updates.append(entry["name"])

    new_text = "".join(lines)
    if new_text != original_text:
        images_path.write_text(new_text, encoding="utf-8")
    return changes_action, entry_updates, missing_entries


def remove_component_from_images_manifest(images_path, friendly, values_key, paths_to_update, repos, new_tags_by_path):
    """Counterpart to update_images_manifest for a bump that nets out to no
    change from upgrade_docs_baseline at all (see lib.upgradedoc.compute_changed_
    components): still writes each touched entry's final version/digest —
    the manifest's job is to list the correct final state for every image
    regardless of change-tracking — but removes the "changes:" list item
    and each entry's own preceding source comment instead of updating
    them, since there is no longer anything to document. Returns
    (changes_action, entry_names_updated) — changes_action is "removed" or
    None (no matching list item found)."""
    original_text = images_path.read_text(encoding="utf-8")
    lines = original_text.splitlines(keepends=True)

    header_idx, header_has_count = find_images_manifest_changes_header(lines)

    changes_action = None
    if header_idx is not None:
        item_indices = []
        for i in range(header_idx + 1, len(lines)):
            if lines[i].rstrip("\n") == "#" or not lines[i].startswith("#"):
                break
            if re.match(r"^#\s*\d+\.", lines[i]):
                item_indices.append(i)

        norm_friendly = normalize_name(friendly)
        match_idx = None
        for idx in item_indices:
            m = CHANGES_ITEM_RE.match(lines[idx])
            if m and norm_friendly in normalize_name(m.group("rest")):
                match_idx = idx
                break

        if match_idx is not None:
            del lines[match_idx]
            remaining_indices = [i - 1 if i > match_idx else i for i in item_indices if i != match_idx]
            for new_num, idx in enumerate(remaining_indices, start=1):
                m = CHANGES_ITEM_RE.match(lines[idx])
                lines[idx] = f"#   {new_num}. {m.group('rest')}\n"
            remaining = len(remaining_indices)
            if header_has_count:
                count_word = NUMBER_WORDS[remaining] if remaining < len(NUMBER_WORDS) else str(remaining)
                noun = "change" if remaining == 1 else "changes"
                header_m = CHANGES_HEADER_RE.match(lines[header_idx])
                lines[header_idx] = f"{header_m.group('indent')}{count_word} {noun}:\n"
            # else: bare "# Changes:" header — left as-is, same convention
            # update_images_manifest's own insertion path follows.
            changes_action = "removed"

    entries = yaml.safe_load("".join(lines)) or []
    if not isinstance(entries, list):
        entries = []
    entry_line_indices = [i for i, line in enumerate(lines) if re.match(r"^-\s*name:", line)]

    def component_of(entry):
        return values_key if normalize_name(values_key) in normalize_name(entry["name"]) else None

    def same_group(entry_a, entry_b):
        return (
            component_of(entry_a) is not None
            and component_of(entry_a) == component_of(entry_b)
            and entry_a.get("version") == entry_b.get("version")
        )

    entry_updates, comment_lines_to_remove = [], []
    for path in paths_to_update:
        target_path = values_tree_path_for(values_key, path)
        entry, entry_idx, index = find_matching_images_entry(entries, entry_line_indices, target_path)
        if entry is None:
            continue
        new_app_version, digest = new_tags_by_path[path].split("@", 1)
        block_end2 = len(lines)
        for i in range(entry_idx + 1, len(lines)):
            if re.match(r"^-\s*name:", lines[i]) or not lines[i].strip():
                block_end2 = i
                break
        for i in range(entry_idx, block_end2):
            m = re.match(r"^\s*(version|digest):", lines[i])
            if not m:
                continue
            new_value = new_app_version if m.group(1) == "version" else digest
            lines[i] = replace_scalar_value(lines[i], new_value)

        comment_idx = find_grouped_preceding_comment_line(lines, entries, entry_line_indices, index, same_group)
        if comment_idx is not None and extract_source_version(lines[comment_idx]):
            comment_lines_to_remove.append(comment_idx)
        entry_updates.append(entry["name"])

    for idx in sorted(set(comment_lines_to_remove), reverse=True):
        del lines[idx]

    new_text = "".join(lines)
    if new_text != original_text:
        images_path.write_text(new_text, encoding="utf-8")
    return changes_action, entry_updates
