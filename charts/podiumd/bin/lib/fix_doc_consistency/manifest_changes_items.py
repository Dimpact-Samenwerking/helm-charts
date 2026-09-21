"""fix-doc-consistency's own images-manifest "# Changes:" header-list
maintenance (dedupe + reorder), split out of that script for pylint's
too-many-lines check."""

from lib.component_docs.images_manifest_changes_header import (
    CHANGES_HEADER_RE,
    CHANGES_ITEM_RE,
    NUMBER_WORDS,
    find_images_manifest_changes_header,
)
from lib.docs_consistency.images_manifest_format import match_changes_item_to_entry
from lib.upgradedoc.images_manifest_ordering import match_changes_item_display_name


def dedupe_images_manifest_changes_items(lines):
    """Remove an exact-duplicate item from the images-manifest's own "#
    Changes:" numbered list — the real bug a multi-image "lockstep"
    component (zgw-office-addin's frontend + backend, eck-stack's
    elasticsearch + kibana, internetaakafhandeling's web + poller — see
    settings.yaml's component_resolution.image_paths/version_paths)
    could trigger before
    add_missing_images_manifest_entries' own per-path loop learned to
    check for an already-mentioned name: several missing_paths sharing
    ONE path_display_name each got their own header item inserted,
    identical text and all, even though they're one logical change.

    Compares each item's FULL text (its own first line's "rest" plus any
    wrapped continuation line(s), the same shape sort_images_manifest_
    changes_items' own item blocks use) verbatim — the first occurrence
    of a given text wins, every later exact repeat is dropped outright
    (nothing distinguishes them worth keeping, so there's nothing to
    merge). Remaining items are renumbered 1..N, and the header's own
    leading count word (if it has one) is updated to match. Mutates
    `lines` in place. Returns the list of removed item texts — empty if
    nothing was a duplicate, or the header doesn't exist."""
    header_idx, header_has_count = find_images_manifest_changes_header(lines)
    if header_idx is None:
        return []

    item_starts = []
    block_end = header_idx + 1
    for i in range(header_idx + 1, len(lines)):
        if lines[i].rstrip("\n") == "#" or not lines[i].startswith("#"):
            break
        block_end = i + 1
        if CHANGES_ITEM_RE.match(lines[i]):
            item_starts.append(i)
    if not item_starts:
        return []

    item_ends = item_starts[1:] + [block_end]
    seen = set()
    keep_chunks = []
    removed = []
    for start, end in zip(item_starts, item_ends, strict=False):
        rest = CHANGES_ITEM_RE.match(lines[start]).group("rest")
        full_text = rest + "".join(lines[start + 1 : end])
        if full_text in seen:
            removed.append(rest)
            continue
        seen.add(full_text)
        keep_chunks.append(lines[start:end])

    if not removed:
        return []

    new_block = []
    for slot, chunk in enumerate(keep_chunks):
        chunk = list(chunk)
        chunk[0] = CHANGES_ITEM_RE.sub(lambda m, n=slot + 1: f"#   {n}. {m.group('rest')}", chunk[0])
        new_block.extend(chunk)
    lines[item_starts[0] : block_end] = new_block

    if header_has_count:
        total = len(keep_chunks)
        count_word = NUMBER_WORDS[total] if total < len(NUMBER_WORDS) else str(total)
        noun = "change" if total == 1 else "changes"
        header_m = CHANGES_HEADER_RE.match(lines[header_idx])
        lines[header_idx] = f"{header_m.group('indent')}{count_word} {noun}:\n"
    return removed


def sort_images_manifest_changes_items(lines, entries, entry_positions, display_name_positions=None):
    """Reorder the images-manifest's own "# Changes:" numbered item list
    (see _find_images_manifest_changes_header) to MIRROR the entry
    list's own final order (entry_positions — see lib.upgradedoc.
    images_manifest_entry_positions, computed from the SAME group-level
    sort sort_images_manifest_entries itself applies) — never a second,
    independently-computed order. An earlier version sorted items via
    component_order_key's own fuzzy match_dependency, the same function
    -upgrade.md's own "### ..." Changes headings use — but a Changes
    item's free-form prose can mention an unrelated dependency's name
    only incidentally (real case: "Keycloak app image 26.6.4 -> 26.7.2
    (keycloak-operator chart unchanged, ...)" fuzzy-matched dependency
    "keycloak-operator" via that parenthetical aside alone, landing it
    BEFORE that dependency's own real sidecars instead of after
    "keycloak"'s own actual entry) — a mismatch the entry list itself
    can never have, since it resolves entries via repo_map/values-tree
    paths, not prose. Each item is matched EXACTLY first, by display
    name (see lib.upgradedoc.match_changes_item_display_name and its own
    display_name_positions — images_manifest_display_name_positions, computed the
    SAME group-level way entry_positions is) — the only reliable option
    for a display name sharing no word at all with its own entry's
    repository basename (real case: "kiss" and "kiss-eck" share nothing
    with their own images' basenames "kiss-frontend" and "elasticsearch"
    /"kibana", so match_changes_item_to_entry's own fuzzy basename-in-
    text search could never resolve them — landing "kiss"/"kiss-eck"'s
    own primary items far from their real sidecars despite the ENTRY
    list itself already grouping them correctly). display_name_
    positions defaults to None (falls straight through to the fuzzy
    path below) for a caller with no deps/values/repo_map/canonical_
    names handy. Falls back to lib.docs_consistency.match_changes_item_
    to_entry (the SAME resolution check_images_manifest_format's own
    Changes-item check already uses) only when the exact match finds
    nothing — free-form hand-written prose that never repeats any
    entry's own display name verbatim. An item resolving via NEITHER
    sorts last, never dragged around by a real item's move. A wrapped
    continuation line (parse_changes_block's own 2-space-indented shape)
    travels WITH its own item, never split from it. Items are renumbered
    1..N to match their new position. Mutates `lines` in place. Returns
    [(item_text, old_position, new_position)] (1-based) for every item
    that actually moved — empty (lines untouched) if the header doesn't
    exist or has fewer than 2 items."""
    header_idx, _header_has_count = find_images_manifest_changes_header(lines)
    if header_idx is None:
        return []

    item_starts = []
    block_end = header_idx + 1
    for i in range(header_idx + 1, len(lines)):
        if lines[i].rstrip("\n") == "#" or not lines[i].startswith("#"):
            break
        block_end = i + 1
        if CHANGES_ITEM_RE.match(lines[i]):
            item_starts.append(i)
    if len(item_starts) < 2:
        return []

    item_ends = item_starts[1:] + [block_end]
    items = []
    for start, end in zip(item_starts, item_ends, strict=False):
        rest = CHANGES_ITEM_RE.match(lines[start]).group("rest")
        display_name = match_changes_item_display_name(rest, display_name_positions or {})
        if display_name is not None:
            position = display_name_positions[display_name]
        else:
            entry = match_changes_item_to_entry(rest, entries)
            position = entry_positions.get(entry["name"], len(entry_positions)) if entry else len(entry_positions)
        items.append({"start": start, "end": end, "rest": rest, "key": position})

    order = sorted(range(len(items)), key=lambda i: items[i]["key"])
    moved = [(items[i]["rest"], i + 1, slot + 1) for slot, i in enumerate(order) if i != slot]
    if not moved:
        return []

    original_chunks = [lines[it["start"] : it["end"]] for it in items]
    new_block = []
    for slot, i in enumerate(order):
        chunk = list(original_chunks[i])
        chunk[0] = CHANGES_ITEM_RE.sub(lambda m, n=slot + 1: f"#   {n}. {m.group('rest')}", chunk[0])
        new_block.extend(chunk)

    lines[item_starts[0] : block_end] = new_block
    return moved
