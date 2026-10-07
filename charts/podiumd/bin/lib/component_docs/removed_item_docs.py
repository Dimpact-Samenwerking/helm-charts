"""The -upgrade.md row and "### ..." section of each removed component or image.

fix-doc-consistency writes them with sync_removed_items; verify-podiumd
reports what it would change through fix-doc-consistency's dry-run.
"""

import re

from collections.abc import Collection
from collections.abc import Sequence

from lib.component_docs.changes_section import INTRO_REMOVED
from lib.component_docs.changes_section import changes_body_kinds
from lib.component_docs.changes_section import insert_changes_section
from lib.component_docs.changes_section import new_row_insert_index
from lib.component_docs.changes_section import remove_changes_block
from lib.component_docs.changes_section import replace_changes_block
from lib.upgradedoc.removed_items import RemovedItem
from lib.upgradedoc.removed_items import removed_item_named
from lib.upgradedoc.sorting_and_ordering import OrderingContext
from lib.upgradedoc.sorting_and_ordering import parse_upgrade_doc_changes_blocks
from lib.upgradedoc.string_and_parsing_basics import parse_upgrade_doc_rows
from lib.upgradedoc.string_and_parsing_basics import set_row_cells
from lib.upgradedoc.string_and_parsing_basics import table_cells
from lib.upgradedoc.string_and_parsing_basics import text_names

REMOVED = "(removed)"


def _removed_cell(version: str | None) -> str:
    return f"{version} {REMOVED}" if version else "-"


# _removed_cell's output, for recognising a row _sync_row wrote.
_REMOVED_CELL_RE = re.compile(rf"\S+ {re.escape(REMOVED)}")


def removed_row_cells(item: RemovedItem) -> tuple[str, str]:
    """The App version and Helm chart cells of a removed item's row."""
    return _removed_cell(item.old_app), _removed_cell(item.old_chart)


def _is_generated_removed_row(cells: list[str]) -> bool:
    """A row as _sync_row writes it: removed_row_cells version cells, at least one removed, and Notes "-"."""
    versions = cells[1:3]
    return (
        len(cells) == 4
        and cells[3] == "-"
        and all(cell == "-" or _REMOVED_CELL_RE.fullmatch(cell) for cell in versions)
        and any(_REMOVED_CELL_RE.fullmatch(cell) for cell in versions)
    )


def removed_section(item: RemovedItem, target: str) -> str:
    """The "### ..." Changes section; it has no image pointer, the image is in no manifest."""
    old = item.old_app or item.old_chart or "-"
    intro = INTRO_REMOVED.format(target=target, name=item.name, old=old)
    return f"### {item.name} {old} {REMOVED}\n\n{intro}\n\n"


def _sync_row(text: str, item: RemovedItem, ordering: OrderingContext) -> str:
    """`text` with `item`'s row added in order, or its version cells rewritten; the Notes cell stays."""
    lines = text.splitlines(keepends=True)
    rows = parse_upgrade_doc_rows(text)
    app, chart = removed_row_cells(item)
    # The same name match as _sync_section, so a hand-written "KISS" row is this item's row.
    row = next((r for r in rows if removed_item_named(r["name"], {item.name: item}) is not None), None)
    if row is None:
        insert_at = new_row_insert_index(lines, rows, item.name, ordering)
        if insert_at is None:
            return text
        lines.insert(insert_at, f"| {item.name} | {app} | {chart} | - |\n")
        return "".join(lines)
    set_row_cells(lines, row, app, chart)
    return "".join(lines)


def _sync_section(text: str, item: RemovedItem, target: str, ordering: OrderingContext) -> str:
    """`text` with `item`'s section added in order, or its generated parts rewritten; user text stays."""
    section = removed_section(item, target)
    block = next(
        (b for b in parse_upgrade_doc_changes_blocks(text) if removed_item_named(b["heading"], {item.name: item})),
        None,
    )
    if block is None:
        # A section inserted last keeps its trailing blank line, which a rewrite would drop.
        return insert_changes_section(text, section, item.name, ordering).rstrip("\n") + "\n"
    return replace_changes_block(text, block, section)


def _drop_stale_removed_items(
    text: str, items: Sequence[RemovedItem], gone_row_names: Collection[str]
) -> tuple[str, list[str]]:
    """`text` without generated rows and section parts that no longer apply.

    These are an item no longer removed vs the baseline (after a rebase the
    new baseline may not have it either), and an image of a removed component
    (gone_row_names), which an earlier bump in the cycle may have documented.
    User text stays, to resolve by hand; so does a row with a Notes cell.
    Returns (text, row names and section headings dropped).
    """
    by_name = {item.name: item for item in items}
    dropped: list[str] = []
    lines = text.splitlines(keepends=True)
    for row in reversed(parse_upgrade_doc_rows(text)):
        cells = table_cells(lines[row["line_index"]])
        stale = removed_item_named(row["name"], by_name) is None and _is_generated_removed_row(cells)
        if stale or (row["name"] in gone_row_names and cells[-1] == "-"):
            del lines[row["line_index"]]
            dropped.append(row["name"])
    text = "".join(lines)
    for block in reversed(parse_upgrade_doc_changes_blocks(text)):
        body = text.splitlines(keepends=True)[block["start"] + 1 : block["end"]]
        stale = removed_item_named(block["heading"], by_name) is None and "removed" in changes_body_kinds(body)
        if stale or any(text_names(block["heading"], name) for name in gone_row_names):
            text, _removed, _kept_user_text = remove_changes_block(text, block)
            dropped.append(block["heading"])
    return text, dropped


def sync_removed_items(
    text: str,
    items: Sequence[RemovedItem],
    target: str,
    ordering: OrderingContext,
    gone_row_names: Collection[str] = (),
) -> tuple[str, list[str]]:
    """Write each removed item's row and section, and drop the stale ones (see _drop_stale_removed_items).

    gone_row_names: removed_component_image_names. Returns (text, names of the items whose parts changed).
    """
    text, changed = _drop_stale_removed_items(text, items, gone_row_names)
    for item in items:
        new_text = _sync_section(_sync_row(text, item, ordering), item, target, ordering)
        if new_text != text:
            changed.append(item.name)
            text = new_text
    return text, changed
