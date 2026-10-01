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
from lib.upgradedoc.string_and_parsing_basics import match_located_line
from lib.upgradedoc.string_and_parsing_basics import parse_upgrade_doc_rows


class ChangesItem(TypedDict):
    """One "# Changes:" item: line span (start, exclusive end), text after the number, sort key."""

    start: int
    end: int
    rest: str
    key: int


def _renumbered_changes_block(chunks: list[list[str]]) -> list[str]:
    """Renumber item chunks 1..N in list order and return the concatenated lines."""
    new_block: list[str] = []
    for slot, chunk in enumerate(chunks):
        chunk = list(chunk)
        chunk[0] = CHANGES_ITEM_RE.sub(lambda m, n=slot + 1: f"#   {n}. {m.group('rest')}", chunk[0])
        new_block.extend(chunk)
    return new_block


def _deduped_item_chunks(lines: list[str], spans: list[tuple[int, int]]) -> tuple[list[list[str]], list[str]]:
    """Drop later verbatim repeats of an item's full text (incl. continuations).

    Returns (keep_chunks, removed_rest_texts)."""
    seen: set[str] = set()
    keep_chunks: list[list[str]] = []
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

    lines[spans[0][0] : block_end] = _renumbered_changes_block(keep_chunks)
    if header_has_count:
        _update_changes_header_count(lines, header_idx, len(keep_chunks))
    return removed


def sort_images_manifest_changes_items(
    lines: list[str], display_name_positions: dict[str, int]
) -> list[tuple[str, int, int]]:
    """Reorder "# Changes:" items by changes_item_order_keys, as the checker orders them.

    Continuation lines move with their item; items are renumbered.

    Mutates `lines`. Returns [(item_text, old_pos, new_pos)] (1-based) for
    moved items; empty if no header or fewer than 2 items."""
    header_idx, _header_has_count = find_images_manifest_changes_header(lines)
    if header_idx is None:
        return []

    spans, block_end = images_manifest_changes_item_spans(lines, header_idx)
    if len(spans) < 2:
        return []

    rests = [match_located_line(CHANGES_ITEM_RE, lines[start]).group("rest") for start, _end in spans]
    keys = changes_item_order_keys(rests, display_name_positions)
    items: list[ChangesItem] = [
        {"start": start, "end": end, "rest": rest, "key": key}
        for (start, end), rest, key in zip(spans, rests, keys, strict=True)
    ]

    order = sorted(range(len(items)), key=lambda i: items[i]["key"])
    moved = [(items[i]["rest"], i + 1, slot + 1) for slot, i in enumerate(order) if i != slot]
    if not moved:
        return []

    ordered_chunks = [lines[items[i]["start"] : items[i]["end"]] for i in order]
    lines[spans[0][0] : block_end] = _renumbered_changes_block(ordered_chunks)
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
    lines = images_path.read_text(encoding="utf-8").splitlines(keepends=True)
    fixed = fix_stale_changes_items(lines, expected_changes_items(row_names, canonical_names, resolution))
    if fixed:
        images_path.write_text("".join(lines), encoding="utf-8")
    return fixed
