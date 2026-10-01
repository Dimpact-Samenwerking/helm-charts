"""Canonical values.yaml-order sorting for upgrade-doc table rows, Changes blocks and values-deltas sections."""

import re

from collections.abc import Mapping
from collections.abc import Sequence
from itertools import pairwise
from typing import TypedDict
from typing import TypeVar

from lib.chart.chart_yaml import ChartDependency
from lib.chart.registered_paths import native_components
from lib.chart.values_tree_primitives import values_key_of
from lib.upgradedoc.string_and_parsing_basics import changes_heading_identities
from lib.upgradedoc.string_and_parsing_basics import match_canonical_sidecar_name
from lib.upgradedoc.string_and_parsing_basics import match_dependency
from lib.upgradedoc.string_and_parsing_basics import match_located_line
from lib.upgradedoc.string_and_parsing_basics import match_native_component
from lib.upgradedoc.string_and_parsing_basics import parse_upgrade_doc_rows
from lib.yaml_types import YamlMapping

CHANGES_BLOCK_HEADING_RE = re.compile(r"^###\s+(.+)$")


VALUES_DELTA_SECTION_HEADING_RE = re.compile(r"^##\s+(.+?)\s*$")

OrderKeyT = TypeVar("OrderKeyT", int, tuple[int, ...])


class HeadingBlock(TypedDict):
    """One heading's line span: start is the heading's 0-based index, end is exclusive."""

    heading: str
    start: int
    end: int


def values_key_order(values: YamlMapping | None):
    """Top-level keys of values.yaml in file order (safe_load preserves insertion order)."""
    return list(values.keys()) if isinstance(values, dict) else []


def values_tree_position(values: YamlMapping, path: tuple[str, ...]) -> tuple[int, ...]:
    """The nested position of path within values: one key index per segment.

    E.g. (0, 0, 3) for ("global", "images", "redis"). Sorting by the full position
    rather than the top-level key keeps peers such as the global.images.* entries
    in values.yaml order. A segment not found ends the tuple with an index that
    sorts after every real sibling. A prefix path sorts before its extensions, so
    a dependency's own row sorts before its nested sidecars."""
    position: list[int] = []
    node = values
    for segment in path:
        if not isinstance(node, dict) or segment not in node:
            position.append(len(node) if isinstance(node, dict) else 0)
            break
        position.append(list(node.keys()).index(segment))
        node = node[segment]
    return tuple(position)


def component_order_key(
    name: str,
    deps: list[ChartDependency],
    key_order: list[str],
    canonical_names: Mapping[str, tuple[str, ...]] | None = None,
    values: YamlMapping | None = None,
) -> tuple[int, ...]:
    """Sort key for a doc item (table row name or "### ..." Changes heading).

    Returns (values_key_index, is_sidecar): the index in key_order of the
    top-level key name resolves to (via match_dependency, then
    match_native_component), or len(key_order) if unresolved. is_sidecar puts a
    "<parent> - <image-basename>" name after its parent, which resolves to the same key.

    canonical_names is consulted only when no dependency matches, so a bare
    global shared-image name (e.g. "nginx-unprivileged") sorts at its real
    position instead of last. With values also given, such a name returns
    (values_key_index, *nested position) so peers under the same key (e.g.
    global.images.*) keep values.yaml order instead of tying."""
    dep = match_dependency(name, deps)
    values_key = values_key_of(dep) if dep else None
    is_sidecar = 1 if " - " in name else 0
    sidecar_path = None
    if values_key is None:
        values_key = match_native_component(name, native_components())
    if values_key is None and canonical_names is not None:
        sidecar_path = match_canonical_sidecar_name(name, canonical_names)
        if sidecar_path:
            values_key = sidecar_path[0]
    if values_key is None:
        return (len(key_order), is_sidecar)
    try:
        idx = key_order.index(values_key)
    except ValueError:
        return (len(key_order), is_sidecar)
    if sidecar_path is not None and values is not None:
        return (idx, *values_tree_position(values, sidecar_path)[1:])
    return (idx, is_sidecar)


def find_out_of_order_names(
    names: list[str],
    deps: list[ChartDependency],
    key_order: list[str],
    canonical_names: Mapping[str, tuple[str, ...]] | None = None,
    values: YamlMapping | None = None,
) -> list[tuple[str, str]]:
    """Every adjacent (a, b) pair whose component_order_key order is inverted.

    Adjacent pairs suffice to detect any non-monotonic sequence. Unresolved names
    share one sentinel key and never flag each other. Without values, canonical
    sidecar names under the same top-level key tie and are never flagged."""
    violations: list[tuple[str, str]] = []
    for a, b in pairwise(names):
        if component_order_key(b, deps, key_order, canonical_names, values) < component_order_key(
            a, deps, key_order, canonical_names, values
        ):
            violations.append((a, b))
    return violations


def insertion_index(new_key: OrderKeyT, existing_keys: list[OrderKeyT]) -> int:
    """Index in existing_keys before the first key greater than new_key, or the end.

    Items sharing the unmatched sentinel key keep a new item after them."""
    for i, k in enumerate(existing_keys):
        if k > new_key:
            return i
    return len(existing_keys)


def component_insertion_index(
    new_name: str,
    existing_names: Sequence[str],
    deps: list[ChartDependency],
    values: YamlMapping | None,
    canonical_names: Mapping[str, tuple[str, ...]] | None = None,
) -> int:
    """insertion_index of new_name among existing_names, each keyed by component_order_key in values.yaml order."""
    key_order = values_key_order(values)

    def order_key(name: str):
        return component_order_key(name, deps, key_order, canonical_names, values)

    return insertion_index(order_key(new_name), [order_key(name) for name in existing_names])


def changes_section_bounds(lines: list[str]) -> tuple[int | None, int]:
    """(changes_idx, section_end) for "## Changes"; (None, len(lines)) if absent.

    section_end is the next "## " heading or len(lines)."""
    changes_idx = None
    for i, line in enumerate(lines):
        if line.strip() == "## Changes":
            changes_idx = i
            break
    if changes_idx is None:
        return None, len(lines)
    section_end = len(lines)
    for i in range(changes_idx + 1, len(lines)):
        if re.match(r"^##\s+\S", lines[i]):
            section_end = i
            break
    return changes_idx, section_end


def parse_upgrade_doc_changes_blocks(text: str) -> list[HeadingBlock]:
    """HeadingBlocks for each "### ..." item under "## Changes"; [] if no such section.

    end is the next "### "/"## " heading or EOF. "#### ..." sub-headings stay part
    of their block."""
    lines = text.splitlines(keepends=True)
    changes_idx, section_end = changes_section_bounds(lines)
    if changes_idx is None:
        return []

    heading_indices = [i for i in range(changes_idx + 1, section_end) if CHANGES_BLOCK_HEADING_RE.match(lines[i])]
    blocks: list[HeadingBlock] = []
    for j, start in enumerate(heading_indices):
        end = heading_indices[j + 1] if j + 1 < len(heading_indices) else section_end
        blocks.append(
            {
                "heading": match_located_line(CHANGES_BLOCK_HEADING_RE, lines[start]).group(1),
                "start": start,
                "end": end,
            }
        )
    return blocks


def changes_blocks_with_lines(text: str) -> tuple[list[str], list[HeadingBlock]]:
    """(text's lines with line ends, its "### ..." blocks under "## Changes"), for scans that index both."""
    return text.splitlines(keepends=True), parse_upgrade_doc_changes_blocks(text)


def block_for_component(
    blocks: list[HeadingBlock],
    friendly: str,
    deps: list[ChartDependency],
    canonical_names: Mapping[str, tuple[str, ...]] | None,
) -> HeadingBlock | None:
    """The block whose heading names exactly `friendly`'s component(s), as check_docs_consistency pairs them.

    Exact, so a sidecar's block is never taken for its parent's and a block
    covering several components never matches one of them.
    """
    target = changes_heading_identities(friendly, deps, canonical_names)
    if not target:
        return None
    return next((b for b in blocks if changes_heading_identities(b["heading"], deps, canonical_names) == target), None)


def sort_upgrade_doc_rows(
    text: str,
    deps: list[ChartDependency],
    values: YamlMapping,
    canonical_names: Mapping[str, tuple[str, ...]] | None = None,
) -> tuple[str, list[tuple[str, int, int]]]:
    """Reorder the "Component versions" table rows into values.yaml order.

    Returns (new_text, moved), moved being [(name, old_pos, new_pos)] (1-based)
    for rows that moved; empty with text unchanged if already sorted or fewer
    than 2 rows. Row content is never changed."""
    rows = parse_upgrade_doc_rows(text)
    if len(rows) < 2:
        return text, []

    key_order = values_key_order(values)
    names = [row["name"] for row in rows]
    order = sorted(
        range(len(names)), key=lambda i: component_order_key(names[i], deps, key_order, canonical_names, values)
    )
    moved = [(names[i], i + 1, slot + 1) for slot, i in enumerate(order) if i != slot]
    if not moved:
        return text, []

    lines = text.splitlines(keepends=True)
    slots = [row["line_index"] for row in rows]
    original_lines = [lines[slot] for slot in slots]
    for slot, i in zip(slots, order, strict=True):
        lines[slot] = original_lines[i]
    return "".join(lines), moved


def sort_changes_blocks(
    text: str,
    deps: list[ChartDependency],
    values: YamlMapping,
    canonical_names: Mapping[str, tuple[str, ...]] | None = None,
) -> tuple[str, list[tuple[str, int, int]]]:
    """Reorder the "## Changes" "### ..." blocks into values.yaml order.

    Returns (new_text, moved) as sort_upgrade_doc_rows does."""
    blocks = parse_upgrade_doc_changes_blocks(text)
    if len(blocks) < 2:
        return text, []

    key_order = values_key_order(values)
    headings = [b["heading"] for b in blocks]
    order = sorted(
        range(len(headings)), key=lambda i: component_order_key(headings[i], deps, key_order, canonical_names, values)
    )
    moved = [(headings[i], i + 1, slot + 1) for slot, i in enumerate(order) if i != slot]
    if not moved:
        return text, []

    lines = text.splitlines(keepends=True)
    original_texts = ["".join(lines[b["start"] : b["end"]]) for b in blocks]
    new_texts = [original_texts[i] for i in order]

    prefix = "".join(lines[: blocks[0]["start"]])
    suffix = "".join(lines[blocks[-1]["end"] :])
    return prefix + "".join(new_texts) + suffix, moved


def parse_values_delta_sections(text: str) -> list[HeadingBlock]:
    """HeadingBlocks for every top-level "## ..." section of a values-deltas doc.

    end is the next "## " heading or EOF. Content before the first "## " heading
    belongs to no section."""
    lines = text.splitlines(keepends=True)
    heading_indices = [i for i, line in enumerate(lines) if VALUES_DELTA_SECTION_HEADING_RE.match(line)]
    sections: list[HeadingBlock] = []
    for j, start in enumerate(heading_indices):
        end = heading_indices[j + 1] if j + 1 < len(heading_indices) else len(lines)
        sections.append(
            {
                "heading": match_located_line(VALUES_DELTA_SECTION_HEADING_RE, lines[start]).group(1),
                "start": start,
                "end": end,
            }
        )
    return sections


def sort_values_delta_sections(
    text: str,
    deps: list[ChartDependency],
    values: YamlMapping,
    canonical_names: Mapping[str, tuple[str, ...]] | None = None,
) -> tuple[str, list[tuple[str, int, int]]]:
    """Reorder values-deltas "## ..." sections into values.yaml order.

    Section content is never changed. Returns (new_text, moved) as
    sort_upgrade_doc_rows does."""
    sections = parse_values_delta_sections(text)
    if len(sections) < 2:
        return text, []

    key_order = values_key_order(values)
    headings = [s["heading"] for s in sections]
    order = sorted(
        range(len(headings)), key=lambda i: component_order_key(headings[i], deps, key_order, canonical_names, values)
    )
    moved = [(headings[i], i + 1, slot + 1) for slot, i in enumerate(order) if i != slot]
    if not moved:
        return text, []

    lines = text.splitlines(keepends=True)
    # Strip each section's own trailing blank lines (the last one has none);
    # the join below puts exactly one between sections.
    original_texts = ["".join(lines[s["start"] : s["end"]]).rstrip("\n") + "\n" for s in sections]
    new_texts = [original_texts[i] for i in order]

    prefix = "".join(lines[: sections[0]["start"]])
    suffix = "".join(lines[sections[-1]["end"] :])
    body = "\n".join(new_texts)
    if suffix:
        body += "\n"
    return prefix + body + suffix, moved
