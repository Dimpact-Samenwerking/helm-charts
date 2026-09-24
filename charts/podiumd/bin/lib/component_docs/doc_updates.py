"""The upgrade-doc and values-deltas.md writes that update-component-version
and update-image-version both make for one bumped component, plus the
closing fix-doc-consistency run."""

import sys

from dataclasses import dataclass
from pathlib import Path

from lib.component_docs import NO_CHANGES_CLAIMED_RE
from lib.component_docs.changes_section import OrderingContext
from lib.component_docs.changes_section import VersionChange
from lib.component_docs.changes_section import insert_changes_section
from lib.component_docs.changes_section import remove_changes_section
from lib.component_docs.changes_section import remove_component_row
from lib.component_docs.changes_section import update_component_table
from lib.component_docs.values_delta_sections import ValuesDeltaOrdering
from lib.component_docs.values_delta_sections import insert_values_delta_section
from lib.procutil import run_script

FIX_DOC_CONSISTENCY_SCRIPT = Path(__file__).resolve().parents[2] / "fix-doc-consistency"


@dataclass
class ValuesDeltaEntry:
    """One component's values-deltas.md section: its heading line and the
    describe_key_changes lines under it."""

    friendly: str
    heading_line: str
    key_lines: list[str]


def print_missing_upgrade_doc(upgrade_docs_baseline: str | None, target: str) -> None:
    """Explain why the upgrade doc is skipped: no upgrade_docs baseline
    recorded yet, or no upgrade doc scaffolded for target."""
    print()
    if upgrade_docs_baseline is None:
        print(
            "No release-baseline.yaml upgrade_docs key found — run create-podiumd-version/"
            "change-podiumd-baseline first; skipping doc updates."
        )
    else:
        print(
            f"No upgrade doc found for target {target} — run create-doc-version first to scaffold it; "
            f"skipping doc updates."
        )


def reset_upgrade_doc(
    upgrade_path: Path, friendly: str, ordering: OrderingContext, upgrade_docs_baseline: str | None
) -> None:
    """The component is back at its upgrade_docs_baseline version: remove
    its table row and Changes section from the upgrade doc."""
    text = upgrade_path.read_text(encoding="utf-8")
    new_text, row_removed = remove_component_row(text, friendly)
    new_text, section_removed = remove_changes_section(new_text, friendly, ordering)
    if row_removed or section_removed:
        upgrade_path.write_text(new_text, encoding="utf-8")
    print()
    print(f"=== Updating {upgrade_path.name} ===")
    print(
        f"  {friendly} is back at its upgrade_docs_baseline {upgrade_docs_baseline} version — nothing left to document"
    )
    if row_removed:
        print("  removed table row")
    if section_removed:
        print(f"  removed '### {friendly} ...' Changes section")


def rewrite_upgrade_doc(
    upgrade_path: Path, friendly: str, change: VersionChange, section: str, ordering: OrderingContext
) -> None:
    """Update friendly's table row with change and replace its Changes
    section with section. Rewritten from scratch each time: a later hop
    (e.g. reconsidering 3 for 2) would otherwise leave the original
    "1 -> 3" prose stale while the table row says "1 -> 2"."""
    text = upgrade_path.read_text(encoding="utf-8")
    new_text, table_action = update_component_table(text, friendly, change, ordering)
    if table_action is None:
        return
    new_text, _ = remove_changes_section(new_text, friendly, ordering)
    new_text = insert_changes_section(new_text, section, friendly, ordering)
    upgrade_path.write_text(new_text, encoding="utf-8")
    print()
    print(f"=== Updating {upgrade_path.name} ===")
    print(f"  {table_action} table row")
    print(f"  (re)wrote '### {friendly} ...' Changes section")


def write_values_delta_entry(
    values_deltas_path: Path, text: str, entry: ValuesDeltaEntry, delta_ordering: ValuesDeltaOrdering
) -> None:
    """Insert entry's section into values-deltas.md text and write it,
    noting when the doc claims no gemeente changes are required."""
    no_changes_claimed = bool(NO_CHANGES_CLAIMED_RE.search(text))
    text = insert_values_delta_section(text, entry.friendly, entry.heading_line, entry.key_lines, delta_ordering)
    values_deltas_path.write_text(text, encoding="utf-8")
    print()
    print(f"=== Updating {values_deltas_path.name} ===")
    print(f"  '{entry.heading_line.rstrip()}'")
    for line in entry.key_lines:
        print(f"  {line.rstrip()}")
    if no_changes_claimed:
        print(
            "  note: doc claims 'no gemeente podiumd.yml changes are required' — that's about "
            "gemeente ACTION, not about whether anything changed, so it may still hold; "
            "double-check it's still true now that this bullet's been added"
        )


def write_removed_values_delta_section(values_deltas_path: Path, text: str, friendly: str) -> None:
    """Write values-deltas.md text after its stale section for friendly
    was removed (the bump has no values-schema change to document)."""
    values_deltas_path.write_text(text, encoding="utf-8")
    print()
    print(f"=== Updating {values_deltas_path.name} ===")
    print(f"  removed stale section for {friendly} — no values-schema change to document for this bump")


def complete_docs_and_finish() -> None:
    """Run fix-doc-consistency on the chart's docs, then print the closing
    reminder to re-render before committing."""
    print()
    print("=== Completing the docs (fix-doc-consistency) ===")
    run_script([sys.executable, str(FIX_DOC_CONSISTENCY_SCRIPT)])
    print()
    print("Done. Re-render the chart to confirm (verify-podiumd or /helm-render-all) before committing.")
