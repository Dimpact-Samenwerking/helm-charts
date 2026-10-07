"""The "# Changes:" items docs/images/images-<target>.yaml should have, and their repair."""

import re

from collections.abc import Iterable
from collections.abc import Mapping
from dataclasses import dataclass

from lib.component_docs.changes_section import VersionChange
from lib.component_docs.images_manifest_changes_header import CHANGES_ITEM_RE
from lib.component_docs.images_manifest_changes_header import find_images_manifest_changes_header
from lib.component_docs.images_manifest_changes_header import images_manifest_changes_item_spans
from lib.upgradedoc.grouped_comments_and_changes_block import parse_changes_block
from lib.upgradedoc.images_manifest_ordering import match_changes_item_display_name
from lib.upgradedoc.resolve_component_row import ResolutionContext
from lib.upgradedoc.resolve_component_row import ResolvedRow
from lib.upgradedoc.resolve_component_row import resolve_component_row
from lib.upgradedoc.resolve_component_row import resolved_row_unchanged
from lib.upgradedoc.string_and_parsing_basics import match_located_line
from lib.upgradedoc.string_and_parsing_basics import normalize_version
from lib.upgradedoc.version_cells_and_key_changes import image_manifest_version_text


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
    row_names: Iterable[str],
    manifest_text: str,
    canonical_names: Mapping[str, tuple[str, ...]],
    resolution: ResolutionContext,
) -> dict[str, ExpectedChangesItem]:
    """{name: its expected "# Changes:" item} for each changed upgrade-doc table row and each item without a row.

    Resolved as the table row is (resolve_component_row), so the item can't
    contradict the row. An unchanged row is left out (fix-doc-consistency
    removes it), but an unchanged item without a row is a digest-only re-pin:
    its entry stays, as the list diff counts a new digest as a change. Names
    not fully resolvable are left out.
    """
    rows = list(row_names)
    names = rows + [item["name"] for item in parse_changes_block(manifest_text) if item["name"] not in rows]
    expected: dict[str, ExpectedChangesItem] = {}
    for name in names:
        resolved = resolve_component_row(name, canonical_names, resolution)
        if resolved["kind"] == "unmatched" or resolved["target_app"] is None or resolved["baseline_app"] is None:
            continue
        if resolved["kind"] != "native" and resolved["baseline_resolved"] is not True:
            continue
        digest_only = resolved_row_unchanged(resolved)
        if digest_only and name in rows:
            continue
        item = _expected_changes_item(name, resolved, digest_only=digest_only)
        if item is not None:
            expected[name] = item
    return expected


def _expected_changes_item(name: str, resolved: ResolvedRow, *, digest_only: bool) -> ExpectedChangesItem | None:
    """The item for one resolved name; None for a dependency without both chart versions."""
    chart_clause = None
    chart_changed = False
    if resolved["kind"] == "dependency":
        if resolved["baseline_chart"] is None or resolved["target_chart"] is None:
            return None
        change = VersionChange(
            resolved["baseline_app"], resolved["target_app"], resolved["baseline_chart"], resolved["target_chart"]
        )
        m = _CHART_CLAUSE_RE.search(changes_header_item_text(name, change))
        chart_clause = m.group(1) if m else None
        chart_changed = normalize_version(resolved["baseline_chart"]) != normalize_version(resolved["target_chart"])
    version_text = image_manifest_version_text(
        resolved["baseline_app"], resolved["target_app"], digest_only_change=digest_only
    )
    return ExpectedChangesItem(f"{name} {version_text}", chart_clause, chart_changed)


def stale_changes_items(lines: list[str], expected: Mapping[str, ExpectedChangesItem]) -> list[tuple[int, str, str]]:
    """(line index, current text, expected text) of each one-line "# Changes:" item that contradicts its row.

    An item belongs to the longest row name it names (match_changes_item_display_name),
    so a sidecar item "zac - solr ..." never belongs to row "zac". Its versions must
    match. The "(chart ...)" clause is required when the chart version
    changed; otherwise only checked when present, since an item of an
    unchanged chart is written without it.
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
