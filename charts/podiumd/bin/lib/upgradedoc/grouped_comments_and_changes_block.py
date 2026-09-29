"""Preceding-comment lookup, images-manifest "# Changes:" block parsing,
key-diff primitives, and path_display_name."""

import re

from collections.abc import Callable
from collections.abc import Iterator
from collections.abc import Mapping
from typing import Literal

from lib.chart.chart_yaml import ChartDependency
from lib.chart.registered_paths import is_primary_image_path
from lib.chart.values_tree_primitives import values_key_of
from lib.images_manifest import ManifestEntry
from lib.upgradedoc.string_and_parsing_basics import VersionRow
from lib.upgradedoc.string_and_parsing_basics import extract_source_version
from lib.upgradedoc.string_and_parsing_basics import extract_target_version
from lib.yaml_types import YamlValue

BARE_CHART_CLAUSE_RE = re.compile(
    r"\bchart\s+`?[A-Za-z0-9][\w.\-]*`?\s*(?:→|->)\s*`?[A-Za-z0-9][\w.\-]*`?", re.IGNORECASE
)


VERSION_SPEC_RE = re.compile(
    r"[A-Za-z0-9][\w.\-]*\s*(?:→|->)\s*[A-Za-z0-9][\w.\-]*"
    r"|[A-Za-z0-9][\w.\-]*\s*\((?:new|unchanged|digest changed)\)"
)


def find_preceding_comment(lines: list[str], entry_line_index: int) -> str:
    """The contiguous comment line(s) directly above a "- name: ..." line, joined."""
    comment_lines: list[str] = []
    j = entry_line_index - 1
    while j >= 0 and lines[j].strip().startswith("#"):
        comment_lines.insert(0, lines[j].strip())
        j -= 1
    return " ".join(comment_lines)


def find_preceding_comment_line(lines: list[str], entry_line_index: int) -> int | None:
    """Index of the closest comment line above entry_line_index stating a version spec, or None.

    A spec is an arrow pair or a bare "(new)"/"(unchanged)"/"(digest changed)"
    (VERSION_SPEC_RE). Stops at the first blank/non-comment line."""
    j = entry_line_index - 1
    while j >= 0 and lines[j].strip().startswith("#"):
        if VERSION_SPEC_RE.search(lines[j]):
            return j
        j -= 1
    return None


def find_grouped_preceding_comment(
    lines: list[str],
    entries: list[ManifestEntry],
    entry_line_indices: list[int],
    index: int,
    same_group: Callable[[ManifestEntry, ManifestEntry], bool],
) -> str:
    """The comment describing entries[index]'s version bump.

    Its own preceding comment if any, else that of the previous entry when
    same_group says they share one comment block (e.g. zgw-office-addin's
    frontend + backend). same_group should require the same component and
    declared version, so independently versioned siblings (zac vs zac.opa)
    don't inherit each other's comment."""
    comment = find_preceding_comment(lines, entry_line_indices[index])
    if comment or index == 0:
        return comment
    if not same_group(entries[index], entries[index - 1]):
        return ""
    return find_grouped_preceding_comment(lines, entries, entry_line_indices, index - 1, same_group)


def find_grouped_preceding_comment_line(
    lines: list[str],
    entries: list[ManifestEntry],
    entry_line_indices: list[int],
    index: int,
    same_group: Callable[[ManifestEntry, ManifestEntry], bool],
) -> int | None:
    """Like find_grouped_preceding_comment, but returns the comment's line index."""
    comment_idx = find_preceding_comment_line(lines, entry_line_indices[index])
    if comment_idx is not None or index == 0:
        return comment_idx
    if not same_group(entries[index], entries[index - 1]):
        return None
    return find_grouped_preceding_comment_line(lines, entries, entry_line_indices, index - 1, same_group)


def diff_keys(
    baseline_node: YamlValue, current_node: YamlValue, path: tuple[str, ...] = ()
) -> Iterator[tuple[Literal["added", "removed"], tuple[str, ...]]]:
    """Yield ("added"|"removed", path) for the shallowest differing keys.

    A wholly new/removed block is reported once, matching how values-deltas.md
    documents changes. Scalar value changes are not reported. Keys are sorted
    so pair_renames' pairing is deterministic across processes."""
    if not isinstance(baseline_node, dict) or not isinstance(current_node, dict):
        return
    baseline_keys = set(baseline_node.keys())
    current_keys = set(current_node.keys())
    for key in sorted(current_keys - baseline_keys):
        yield "added", (*path, key)
    for key in sorted(baseline_keys - current_keys):
        yield "removed", (*path, key)
    for key in sorted(baseline_keys & current_keys):
        yield from diff_keys(baseline_node[key], current_node[key], (*path, key))


def flatten_leaf_keys(node: YamlValue) -> set[str]:
    """Leaf key names (not paths) anywhere under a subtree, for rename similarity.

    Keys holding a dict/list are excluded; they'd inflate the similarity ratio."""
    keys: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(value, (dict, list)):
                keys |= flatten_leaf_keys(value)
            else:
                keys.add(key)
    elif isinstance(node, list):
        for item in node:
            keys |= flatten_leaf_keys(item)
    return keys


def _get_at_path(node: YamlValue, path: tuple[str, ...]) -> YamlValue:
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def _find_rename_match(
    add_path: tuple[str, ...], removed_left: list[tuple[str, ...]], baseline_node: YamlValue, current_node: YamlValue
) -> tuple[str, ...] | None:
    """First removed path pairing with add_path as a rename (see pair_renames), or None."""
    add_val = _get_at_path(current_node, add_path)
    for rem_path in removed_left:
        if add_path[:-1] != rem_path[:-1]:
            continue
        rem_val = _get_at_path(baseline_node, rem_path)
        add_keys, rem_keys = flatten_leaf_keys(add_val), flatten_leaf_keys(rem_val)
        similar = bool(add_keys and rem_keys and len(add_keys & rem_keys) / len(add_keys | rem_keys) >= 0.3)
        same_scalar = not isinstance(add_val, (dict, list)) and add_val == rem_val
        if similar or same_scalar:
            return rem_path
    return None


def pair_renames(
    added: list[tuple[str, ...]], removed: list[tuple[str, ...]], baseline_node: YamlValue, current_node: YamlValue
) -> tuple[list[tuple[tuple[str, ...], tuple[str, ...]]], list[tuple[str, ...]], list[tuple[str, ...]]]:
    """Pair added/removed keys at the same parent into renames.

    A pair matches when leaf key names overlap enough (e.g. mi.sftp ->
    mi.transfer) or both hold the same scalar. Returns (renamed, added_left,
    removed_left)."""
    renamed: list[tuple[tuple[str, ...], tuple[str, ...]]] = []
    added_left, removed_left = list(added), list(removed)
    for add_path in list(added_left):
        rem_path = _find_rename_match(add_path, removed_left, baseline_node, current_node)
        if rem_path is not None:
            renamed.append((rem_path, add_path))
            added_left.remove(add_path)
            removed_left.remove(rem_path)
    return renamed, added_left, removed_left


def parse_changes_block(text: str) -> list[VersionRow]:
    """Parse an images manifest's "# Changes:" numbered list into VersionRows, e.g.:
        #   1. ZAC (Zaakafhandelcomponent) 5.0.2 -> 5.4.3 (chart 1.0.297, unchanged).

    Lines with 2+ spaces after "#" are continuations joined onto the current
    item, so a version pair split across a wrap is still found. A
    single-space "#" line ends the current item."""
    items: list[VersionRow] = []
    current = None  # raw text accumulated so far for the item being parsed
    for line in _changes_block_lines(text):
        # "\.\s+", not "\.\s*": a version like "1.17.1" on a continuation line
        # must not look like a new list item.
        m = re.match(r"^#\s*\d+\.\s+(.+)$", line)
        if m:
            if current is not None:
                items.append(_finalize_changes_item(current))
            current = m.group(1)
            continue

        cont_m = re.match(r"^#\s{2,}(\S.*)$", line)
        if cont_m and current is not None:
            current += " " + cont_m.group(1)
        elif current is not None:
            items.append(_finalize_changes_item(current))
            current = None

    if current is not None:
        items.append(_finalize_changes_item(current))
    return items


def _changes_block_lines(text: str):
    """Yield the "#" comment lines after the "# Changes:" heading, up to
    the first non-comment line."""
    in_changes = False
    for line in text.splitlines():
        if not line.startswith("#"):
            if in_changes:
                return
            continue
        if re.match(r"^#\s*Changes:\s*$", line):
            in_changes = True
            continue
        if in_changes:
            yield line


def _finalize_changes_item(rest: str) -> VersionRow:
    # Prose often ends with a period right after the version, which the version
    # regex swallows; stripped below since versions never end in ".".
    chart_m = re.search(r"\(chart\s+([^)]+)\)", rest)
    chart_source = extract_source_version(chart_m.group(1)) if chart_m else None
    chart_target = extract_target_version(chart_m.group(1)) if chart_m else None

    # A bare "chart X -> Y" clause (no parens) is a chart bump, not the app
    # version, whether alone or the first of two pairs; remove it from the
    # text searched for the app version. A parenthesized match above wins.
    app_search_text = rest
    bare_chart_m = BARE_CHART_CLAUSE_RE.search(rest)
    if bare_chart_m:
        if chart_source is None:
            chart_source = extract_source_version(bare_chart_m.group(0))
            chart_target = extract_target_version(bare_chart_m.group(0))
        app_search_text = rest[: bare_chart_m.start()] + " " + rest[bare_chart_m.end() :]

    # Without an arrow, the extractors' fallback would return leftover prose
    # as a fake app version.
    if re.search(r"(?:→|->)", app_search_text):
        app_source = extract_source_version(app_search_text)
        app_target = extract_target_version(app_search_text)
    else:
        app_source = app_target = None

    if app_source:
        app_source = app_source.rstrip(".")
    if app_target:
        app_target = app_target.rstrip(".")
    if chart_source:
        chart_source = chart_source.rstrip(".")
    if chart_target:
        chart_target = chart_target.rstrip(".")

    name = rest
    if app_source:
        idx = app_search_text.find(app_source)
        if idx > 0:
            name = app_search_text[:idx].strip()
    return {
        "name": name,
        "app_source": app_source,
        "app": app_target,
        "chart_source": chart_source,
        "chart": chart_target,
    }


def path_display_name(
    path: tuple[str, ...], deps: list[ChartDependency], canonical_names: Mapping[str, tuple[str, ...]]
) -> str:
    """Doc-facing name for a values-tree image path.

    "<values_key>" for a dependency's primary image, else the name
    canonical_names maps the path to, else the dotted path."""
    by_values_key = {values_key_of(dep): dep for dep in deps}
    dep = by_values_key.get(path[0])
    if dep is not None and is_primary_image_path(path, deps):
        return path[0]
    for name, candidate_path in canonical_names.items():
        if candidate_path == path:
            return name
    return ".".join(path)
