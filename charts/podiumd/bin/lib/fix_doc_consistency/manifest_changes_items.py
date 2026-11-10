"""fix-doc-consistency's images-manifest "# Changes:" list maintenance (dedupe, reorder, stale items)."""

from collections.abc import Mapping
from pathlib import Path
from typing import TypedDict

from lib.component_docs.images_manifest_changes_header import CHANGES_HEADER_RE
from lib.component_docs.images_manifest_changes_header import CHANGES_ITEM_RE
from lib.component_docs.images_manifest_changes_header import NUMBER_WORDS
from lib.component_docs.images_manifest_changes_header import find_images_manifest_changes_header
from lib.component_docs.images_manifest_changes_header import images_manifest_changes_item_spans
from lib.component_docs.images_manifest_entries import expected_changes_items
from lib.component_docs.images_manifest_entries import fix_stale_changes_items
from lib.upgradedoc.images_manifest_ordering import changes_item_order_keys
from lib.upgradedoc.resolve_component_row import ResolutionContext
from lib.upgradedoc.sorting_and_ordering import MovedItem
from lib.upgradedoc.string_and_parsing_basics import match_located_line
from lib.upgradedoc.string_and_parsing_basics import parse_upgrade_doc_rows


class ChangesItem(TypedDict):
    """One "# Changes:" item: line span (start, exclusive end), text after the number, sort key."""

    start: int
    end: int
    rest: str
    key: int


# Fewer items are always in order.
_MIN_ITEMS_TO_SORT = 2

# One "# Changes:" item's lines, continuation lines included.
type ItemChunk = list[str]


def _renumbered_changes_block(chunks: list[ItemChunk]) -> list[str]:
    """Renumber item chunks 1..N in list order and return the concatenated lines."""
    new_block: list[str] = []
    for number, chunk in enumerate(chunks, 1):
        new_block.append(CHANGES_ITEM_RE.sub(rf"#   {number}. \g<rest>", chunk[0]))
        new_block.extend(chunk[1:])
    return new_block


def _replace_block(lines: list[str], start: int, end: int, new_block: list[str]) -> None:
    """lines[start:end] replaced by `new_block`, in place: callers keep using their `lines`."""
    after = lines[end:]
    del lines[start:]
    lines.extend([*new_block, *after])


def _deduped_item_chunks(
    lines: list[str],
    spans: list[tuple[int, int]],
) -> tuple[list[ItemChunk], list[str]]:
    """Drop later verbatim repeats of an item's full text (incl. continuations).

    Returns (keep_chunks, removed_rest_texts)."""
    seen: set[str] = set()
    keep_chunks: list[ItemChunk] = []
    removed: list[str] = []
    for start, end in spans:
        rest = match_located_line(CHANGES_ITEM_RE, lines[start]).group("rest")
        full_text = rest + "".join(lines[start + 1 : end])
        if full_text in seen:
            removed.append(rest)
            continue
        seen.add(full_text)
        keep_chunks.append(lines[start:end])
    return keep_chunks, removed


def _update_changes_header_count(lines: list[str], header_idx: int, total: int):
    """Set the header's count word (e.g. "three changes:") to `total`, in place."""
    count_word = NUMBER_WORDS[total] if total < len(NUMBER_WORDS) else str(total)
    noun = "change" if total == 1 else "changes"
    header_m = match_located_line(CHANGES_HEADER_RE, lines[header_idx])
    lines[header_idx] = f"{header_m.group('indent')}{count_word} {noun}:\n"


def dedupe_images_manifest_changes_items(lines: list[str]) -> list[str]:
    """Remove exact-duplicate "# Changes:" items, renumber, and update the count word.

    Multi-image lockstep components (e.g. zgw-office-addin frontend + backend)
    can otherwise get one identical item per image. Mutates `lines`; returns
    removed item texts."""
    header_idx, header_has_count = find_images_manifest_changes_header(lines)
    if header_idx is None:
        return []

    spans, block_end = images_manifest_changes_item_spans(lines, header_idx)
    if not spans:
        return []

    keep_chunks, removed = _deduped_item_chunks(lines, spans)
    if not removed:
        return []

    _replace_block(lines, spans[0][0], block_end, _renumbered_changes_block(keep_chunks))
    if header_has_count:
        _update_changes_header_count(lines, header_idx, len(keep_chunks))
    return removed


def sort_images_manifest_changes_items(lines: list[str], display_name_positions: dict[str, int]) -> list[MovedItem]:
    """Reorder "# Changes:" items by changes_item_order_keys.

    Continuation lines move with their item; items are renumbered.

    Mutates `lines`. Returns [(item_text, old_pos, new_pos)] (1-based) for
    moved items; empty if no header or fewer than 2 items."""
    header_idx, _header_has_count = find_images_manifest_changes_header(lines)
    if header_idx is None:
        return []

    spans, block_end = images_manifest_changes_item_spans(lines, header_idx)
    if len(spans) < _MIN_ITEMS_TO_SORT:
        return []

    rests = [match_located_line(CHANGES_ITEM_RE, lines[start]).group("rest") for start, _end in spans]
    keys = changes_item_order_keys(rests, display_name_positions)
    items: list[ChangesItem] = [
        {"start": start, "end": end, "rest": rest, "key": key}
        for (start, end), rest, key in zip(spans, rests, keys, strict=True)
    ]

    ordered = sorted(enumerate(items, 1), key=lambda numbered: numbered[1]["key"])
    moved = [
        (item["rest"], old_pos, new_pos) for new_pos, (old_pos, item) in enumerate(ordered, 1) if old_pos != new_pos
    ]
    if not moved:
        return []

    ordered_chunks = [lines[item["start"] : item["end"]] for _old_pos, item in ordered]
    _replace_block(lines, spans[0][0], block_end, _renumbered_changes_block(ordered_chunks))
    return moved


def correct_stale_changes_items(
    images_path: Path, upgrade_path: Path, canonical_names: Mapping[str, tuple[str, ...]], resolution: ResolutionContext
) -> list[tuple[str, str]]:
    """Rewrite images_path's "# Changes:" items that contradict their upgrade-doc table row.

    Returns [(old, new), ...]; writes only when something changed.
    """
    if not upgrade_path.is_file() or not images_path.is_file():
        return []
    row_names = [row["name"] for row in parse_upgrade_doc_rows(upgrade_path.read_text(encoding="utf-8"))]
    text = images_path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    fixed = fix_stale_changes_items(lines, expected_changes_items(row_names, text, canonical_names, resolution))
    if fixed:
        images_path.write_text("".join(lines), encoding="utf-8")
    return fixed
