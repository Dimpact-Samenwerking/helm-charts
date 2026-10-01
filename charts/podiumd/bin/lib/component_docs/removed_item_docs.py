"""The -upgrade.md row and "### ..." section of each removed component or image.

fix-doc-consistency writes them with sync_removed_items; the checker reports
removed_item_issues, which is what sync_removed_items would change.
"""

from collections.abc import Sequence

from lib.component_docs.changes_section import INTRO_REMOVED
from lib.component_docs.changes_section import insert_changes_section
from lib.component_docs.changes_section import new_row_insert_index
from lib.component_docs.changes_section import replace_changes_block
from lib.upgradedoc.removed_items import RemovedItem
from lib.upgradedoc.removed_items import removed_item_named
from lib.upgradedoc.sorting_and_ordering import OrderingContext
from lib.upgradedoc.sorting_and_ordering import parse_upgrade_doc_changes_blocks
from lib.upgradedoc.string_and_parsing_basics import parse_upgrade_doc_rows

REMOVED = "(removed)"


def removed_row_cells(item: RemovedItem) -> tuple[str, str]:
    """The App version and Helm chart cells of a removed item's row."""
    app = f"{item.old_app} {REMOVED}" if item.old_app else "-"
    chart = f"{item.old_chart} {REMOVED}" if item.old_chart else "-"
    return app, chart


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
    row = next((r for r in rows if r["name"] == item.name), None)
    if row is None:
        insert_at = new_row_insert_index(lines, rows, item.name, ordering)
        if insert_at is None:
            return text
        lines.insert(insert_at, f"| {item.name} | {app} | {chart} | - |\n")
        return "".join(lines)
    line = lines[row["line_index"]]
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    cells[1:3] = [app, chart]
    lines[row["line_index"]] = "| " + " | ".join(cells) + " |" + ("\n" if line.endswith("\n") else "")
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


def sync_removed_items(
    text: str, items: Sequence[RemovedItem], target: str, ordering: OrderingContext
) -> tuple[str, list[str]]:
    """Write each removed item's row and section. Returns (text, names of the items whose parts changed)."""
    changed: list[str] = []
    for item in items:
        new_text = _sync_section(_sync_row(text, item, ordering), item, target, ordering)
        if new_text != text:
            changed.append(item.name)
            text = new_text
    return text, changed


def removed_item_issues(
    doc_name: str, text: str, items: Sequence[RemovedItem], target: str, ordering: OrderingContext
) -> list[str]:
    """One finding per removed item whose row or section sync_removed_items would add or rewrite."""
    issues: list[str] = []
    for item in items:
        if _sync_row(text, item, ordering) != text:
            issues.append(f'{doc_name}: removed "{item.name}" has no row, or a stale one, in the table')
        if _sync_section(text, item, target, ordering) != text:
            issues.append(f'{doc_name}: removed "{item.name}" has no "### ..." section, or a stale one')
    return [f"{issue}; run fix-doc-consistency" for issue in issues]
