"""Find, create, number and insert items into the images-manifest "# Changes:" header block."""

import re

from lib.chart.chart_yaml import ChartDependency
from lib.chart.values_tree_primitives import values_key_of
from lib.upgradedoc.sorting_and_ordering import insertion_index
from lib.upgradedoc.sorting_and_ordering import values_tree_position
from lib.upgradedoc.string_and_parsing_basics import changes_item_names
from lib.upgradedoc.string_and_parsing_basics import match_dependency_excluding_sidecar_names
from lib.upgradedoc.string_and_parsing_basics import match_located_line
from lib.yaml_types import YamlMapping

NUMBER_WORDS = [
    "Zero",
    "One",
    "Two",
    "Three",
    "Four",
    "Five",
    "Six",
    "Seven",
    "Eight",
    "Nine",
    "Ten",
    "Eleven",
    "Twelve",
    "Thirteen",
    "Fourteen",
    "Fifteen",
]
CHANGES_HEADER_RE = re.compile(r"^(?P<indent>#\s*)(?P<count_word>\w+)\s+changes?:\s*$", re.IGNORECASE)
# "# Changes:" without a count word: hand-curated headers and IMAGES_STUB_TEMPLATE's fresh one.
BARE_CHANGES_HEADER_RE = re.compile(r"^(?P<indent>#\s*)[Cc]hanges:\s*$")
CHANGES_ITEM_RE = re.compile(r"^#\s*(?P<num>\d+)\.\s+(?P<rest>.+)$")
# Intro line the "# Changes:" header follows; insertion anchor for a missing header.
IMAGES_MANIFEST_INTRO_RE = re.compile(r"^#\s*Images new or changed in podiumd\b.*$", re.IGNORECASE)


def find_images_manifest_changes_header(lines: list[str]):
    """(header_idx, header_has_count) for the "# Changes:" header, counted or bare.

    (None, False) if neither shape is found."""
    for i, line in enumerate(lines):
        if CHANGES_HEADER_RE.match(line):
            return i, True
        if BARE_CHANGES_HEADER_RE.match(line):
            return i, False
    return None, False


def ensure_images_manifest_changes_header(lines: list[str]):
    """Add a bare "# Changes:\n#\n" header after the intro line if the file has none.

    insert_images_manifest_header_item never creates a header, so without this a file that
    lost it silently gets no summary items. Idempotent: call before every insert. No-op
    (never crashes) if the intro line is missing too."""
    header_idx, _has_count = find_images_manifest_changes_header(lines)
    if header_idx is not None:
        return
    for i, line in enumerate(lines):
        if IMAGES_MANIFEST_INTRO_RE.match(line.strip()):
            insert_at = i + 1
            if insert_at < len(lines) and lines[insert_at].strip() == "#":
                insert_at += 1
            lines[insert_at:insert_at] = ["# Changes:\n", "#\n"]
            return


def find_images_manifest_changes_items(lines: list[str]) -> tuple[int | None, bool, list[int]]:
    """(header_idx, header_has_count, item_indices) for the "# Changes:" block.

    item_indices are the "#   N. ..." lines in document order; (None, False, []) without a header."""
    header_idx, header_has_count = find_images_manifest_changes_header(lines)
    if header_idx is None:
        return None, False, []
    item_indices, _block_end = images_manifest_changes_block(lines, header_idx)
    return header_idx, header_has_count, item_indices


def find_changes_item(lines: list[str], item_indices: list[int], name: str) -> int | None:
    """The index of the first item in `item_indices` naming `name`, or None."""
    for idx in item_indices:
        m = CHANGES_ITEM_RE.match(lines[idx])
        if m and changes_item_names(m.group("rest"), name):
            return idx
    return None


def images_manifest_changes_count_word(total: int):
    """(count_word, noun) for the header line: a NUMBER_WORDS entry, else the numeral.

    CHANGES_HEADER_RE's count_word is a single \\w+ token, so never "Twenty Six"."""
    count_word = NUMBER_WORDS[total] if total < len(NUMBER_WORDS) else str(total)
    noun = "change" if total == 1 else "changes"
    return count_word, noun


def renumber_images_manifest_changes_items(lines: list[str]):
    """Renumber the "# Changes:" items to a gapless 1..N in document order and fix the count word.

    Catches gaps the other writers miss (e.g. a hand-removed item). Mutates `lines`; returns
    whether anything changed."""
    header_idx, header_has_count, item_indices = find_images_manifest_changes_items(lines)
    if header_idx is None or not item_indices:
        return False

    changed = False
    for slot, idx in enumerate(item_indices):
        expected = slot + 1
        m = match_located_line(CHANGES_ITEM_RE, lines[idx])
        if int(m.group("num")) != expected:
            lines[idx] = CHANGES_ITEM_RE.sub(lambda mm, n=expected: f"#   {n}. {mm.group('rest')}", lines[idx])
            changed = True

    if header_has_count:
        count_word, noun = images_manifest_changes_count_word(len(item_indices))
        header_m = match_located_line(CHANGES_HEADER_RE, lines[header_idx])
        new_header = f"{header_m.group('indent')}{count_word} {noun}:\n"
        if lines[header_idx] != new_header:
            lines[header_idx] = new_header
            changed = True

    return changed


def images_manifest_order_key(
    key_order: list[str], values_key: str | tuple[str, ...], *, is_sidecar: bool, values: YamlMapping | None = None
) -> tuple[int, ...]:
    """Sort key for a "# Changes:" item by values.yaml top-level order; unknown keys sort last.

    With a path tuple and `values`, the nested position breaks ties between items under the
    same top-level key (e.g. the "global.images.*" images). A bare string or values=None
    orders by top-level key and sidecar flag only."""
    path = values_key if isinstance(values_key, tuple) else (values_key,)
    try:
        idx = key_order.index(path[0])
    except ValueError:
        return (len(key_order), 1 if is_sidecar else 0)
    if values is not None and len(path) > 1:
        return (idx, *values_tree_position(values, path)[1:])
    return (idx, 1 if is_sidecar else 0)


def images_manifest_changes_block(lines: list[str], header_idx: int) -> tuple[list[int], int]:
    """(item_starts, block_end) for the "# Changes:" block at header_idx.

    The block ends at a bare "#" line or the first non-comment line."""
    item_starts: list[int] = []
    block_end = header_idx + 1
    for i in range(header_idx + 1, len(lines)):
        if lines[i].rstrip("\n") == "#" or not lines[i].startswith("#"):
            break
        block_end = i + 1
        if CHANGES_ITEM_RE.match(lines[i]):
            item_starts.append(i)
    return item_starts, block_end


def images_manifest_changes_item_spans(lines: list[str], header_idx: int) -> tuple[list[tuple[int, int]], int]:
    """(spans, block_end) for the "# Changes:" block at header_idx: one
    (start, end) line span per "#   N. ..." item, its wrapped continuation
    lines included (see images_manifest_changes_block)."""
    item_starts, block_end = images_manifest_changes_block(lines, header_idx)
    if not item_starts:
        return [], block_end
    return list(zip(item_starts, [*item_starts[1:], block_end], strict=True)), block_end


def remove_changes_item(lines: list[str], item_indices: list[int], match_idx: int) -> list[int]:
    """Delete the "#   N. ..." item at line match_idx and renumber the
    items after it. Returns the remaining items' line indices."""
    del lines[match_idx]
    remaining_indices = [i - 1 if i > match_idx else i for i in item_indices if i != match_idx]
    for new_num, idx in enumerate(remaining_indices, start=1):
        m = match_located_line(CHANGES_ITEM_RE, lines[idx])
        lines[idx] = f"#   {new_num}. {m.group('rest')}\n"
    return remaining_indices


def insert_images_manifest_header_item(
    lines: list[str], deps: list[ChartDependency], key_order: list[str], new_key: tuple[int, ...], item_text: str
) -> None:
    """Insert "#   N. <item_text>" into the "# Changes:" list at new_key's order position.

    Uses the same ordering as upgrade.md's rows. Items not resolvable to a dependency sort
    last for this purpose only. Mutates `lines`; no-op without a header. Renumbers absolutely
    via renumber_images_manifest_changes_items, which also repairs pre-existing gaps."""
    header_idx, _header_has_count, item_indices = find_images_manifest_changes_items(lines)
    if header_idx is None:
        return

    block_end = images_manifest_changes_block(lines, header_idx)[1]

    item_keys: list[tuple[int, ...]] = []
    for idx in item_indices:
        m = CHANGES_ITEM_RE.match(lines[idx])
        item_dep = match_dependency_excluding_sidecar_names(m.group("rest"), deps) if m else None
        if item_dep is None:
            item_keys.append((len(key_order), 0))
            continue
        item_keys.append(images_manifest_order_key(key_order, values_key_of(item_dep), is_sidecar=False))

    insert_slot = insertion_index(new_key, item_keys)
    insert_line = item_indices[insert_slot] if insert_slot < len(item_indices) else block_end
    # Placeholder number; renumbered below.
    lines.insert(insert_line, f"#   0. {item_text}\n")

    renumber_images_manifest_changes_items(lines)
