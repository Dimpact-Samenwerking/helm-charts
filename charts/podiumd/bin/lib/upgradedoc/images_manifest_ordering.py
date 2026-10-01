"""Images-manifest entry grouping, canonical ordering and out-of-order detection.

Entries sharing one dependency/sidecar group move and stay together."""

import re

from collections.abc import Iterable
from collections.abc import Mapping
from dataclasses import dataclass
from itertools import pairwise

from lib.chart.chart_yaml import ChartDependency
from lib.chart.registered_paths import is_primary_image_path
from lib.images_manifest import ManifestEntry
from lib.images_manifest import try_parse_images_manifest
from lib.upgradedoc.app_version_and_image_paths import ImagePath
from lib.upgradedoc.app_version_and_image_paths import chart_image_paths
from lib.upgradedoc.app_version_and_image_paths import resolve_entry_image_path
from lib.upgradedoc.grouped_comments_and_changes_block import find_grouped_preceding_comment_line
from lib.upgradedoc.grouped_comments_and_changes_block import find_preceding_comment_line
from lib.upgradedoc.grouped_comments_and_changes_block import path_display_name
from lib.upgradedoc.sorting_and_ordering import path_order_key
from lib.upgradedoc.sorting_and_ordering import values_key_order
from lib.upgradedoc.string_and_parsing_basics import changes_item_names
from lib.upgradedoc.string_and_parsing_basics import normalize_name
from lib.upgradedoc.version_cells_and_key_changes import VERSION_PAIR_RE
from lib.yaml_types import YamlMapping

SIDECAR_HEADER_RE = re.compile(r"^#\s{2,}sidecar:\s*(?P<text>.*)$", re.IGNORECASE)

# One _images_manifest_groups group: (entry indices, the first entry's
# values-tree path or None, its display name).
ManifestGroup = tuple[list[int], ImagePath | None, str]


@dataclass
class ParsedManifest:
    """Parsed manifest entries, their "- name:" line indices and the raw lines, kept in lockstep."""

    entries: list[ManifestEntry]
    entry_line_indices: list[int]
    lines: list[str]


@dataclass
class EntryResolution:
    """How to resolve a manifest entry to its values-tree path and display name.

    current_paths is precomputed by the caller (ManifestSortContext carries
    values instead)."""

    deps: list[ChartDependency]
    current_paths: dict[tuple[str, ...], str]
    repo_map: dict[str, tuple[str, ...]]
    canonical_names: dict[str, tuple[str, ...]]


@dataclass
class ManifestSortContext:
    """Shared inputs of the manifest sort/position functions.

    Carries values rather than current_paths because these functions derive
    current_paths from values + deps themselves, including global image paths."""

    deps: list[ChartDependency]
    values: YamlMapping
    repo_map: dict[str, tuple[str, ...]]
    canonical_names: dict[str, tuple[str, ...]]


def entry_component(
    entry: ManifestEntry,
    current_paths: Mapping[tuple[str, ...], str | None],
    repo_map: Mapping[str, tuple[str, ...]] | None,
) -> str | None:
    """The top-level values-tree key an entry resolves to, or None if unresolved."""
    path = resolve_entry_image_path(entry["name"], current_paths.keys(), repo_map)
    return path[0] if path else None


def images_manifest_entries_share_group(
    entry_a: ManifestEntry,
    entry_b: ManifestEntry,
    current_paths: Mapping[tuple[str, ...], str | None],
    repo_map: Mapping[str, tuple[str, ...]] | None,
) -> bool:
    """True when two entries form one shared-comment group: same component and same version.

    Same version is only a proxy for a lockstep bump. Shared by the checker, the
    fixer and the sorter so they agree on grouping."""
    component_a = entry_component(entry_a, current_paths, repo_map)
    return (
        component_a is not None
        and component_a == entry_component(entry_b, current_paths, repo_map)
        and entry_a.get("version") == entry_b.get("version")
    )


def _own_header_top_line(lines: list[str], entry_line_index: int) -> str | None:
    """The raw topmost line of the comment block directly above the entry, or None if none.

    Unlike find_preceding_comment(_line), no version pair is required."""
    j = entry_line_index - 1
    top: str | None = None
    while j >= 0 and lines[j].strip().startswith("#"):
        top = lines[j]
        j -= 1
    return top


def images_manifest_block_start(lines: list[str], entry_line_idx: int) -> int:
    """Index where the entry's physical block starts: its preceding comment block, or the entry line.

    For a comment shared with an earlier entry this lands on that comment, so
    inserting there never splits a group and a sort moves the group as one unit."""
    i = entry_line_idx
    while i > 0 and lines[i - 1].lstrip().startswith("#"):
        i -= 1
    return i


def delete_images_manifest_entry(lines: list[str], entry_line_idx: int) -> None:
    """Deletes the entry block starting at entry_line_idx (its "- name:"
    line up to the next entry, comment or blank line) from `lines`, with
    its own version comment (see find_preceding_comment_line) and any
    comment lines between that and the entry. Comment lines above the
    version comment, e.g. a "# Applicaties" group divider, stay. The
    comment also stays when the next entry directly follows with no
    comment of its own, since that entry shares it. A blank line left
    doubled by the deletion is dropped too, and so is a blank line left
    right below a kept comment, so a divider stays on top of the next
    entry."""
    block_end = entry_line_idx + 1
    while block_end < len(lines):
        line = lines[block_end]
        if not line.strip() or line.lstrip().startswith("#") or re.match(r"^-\s*name:", line):
            break
        block_end += 1
    shares_comment = block_end < len(lines) and re.match(r"^-\s*name:", lines[block_end]) is not None
    comment_idx = None if shares_comment else find_preceding_comment_line(lines, entry_line_idx)
    start = entry_line_idx if comment_idx is None else comment_idx
    del lines[start:block_end]
    if 0 < start < len(lines) and not lines[start].strip():
        above = lines[start - 1]
        if not above.strip() or above.lstrip().startswith("#"):
            del lines[start]
    elif start == len(lines) and start > 0 and not lines[start - 1].strip():
        del lines[start - 1]


def header_name_segment(text: str) -> str:
    """A header's component-name part: the text before its version pair, with trailing dashes stripped.

    Also used for "### ..." Changes headings. Compare the result for exact
    equality, not startswith: "redis-operator - redis" is a prefix of
    "redis-operator - redis-exporter".

    Without a version pair (e.g. "<name> 3.14.7-slim (digest changed)") trailing
    "(...)" asides are stripped from the end, repeatedly, then a bare trailing
    version token. That token is only stripped when an aside was present, so a
    bare-name header never loses its last word. Asides are never cut at the
    first "(": names like "mi-data (MI-data exports)" contain one."""
    m = VERSION_PAIR_RE.search(text)
    if m:
        return text[: m.start()].rstrip(" \t—-")
    without_trailing_asides = re.sub(r"(\s*\([^)]*\))+$", "", text)
    if without_trailing_asides == text:
        return text.rstrip(" \t—-")
    bare_version = re.search(r"\s[A-Za-z0-9][\w.\-]*$", without_trailing_asides)
    name = without_trailing_asides[: bare_version.start()] if bare_version else text
    return name.rstrip(" \t—-")


def find_images_manifest_faulty_headers(
    manifest: ParsedManifest, resolution: EntryResolution
) -> list[tuple[str, str, str]]:
    """[(entry_name, expected_display_name, problem), ...] for sidecar entries with a bad own header.

    problem is:
    - "missing": no own indented "#   sidecar: ..." header directly above; the
      entry may be silently sharing a preceding entry's header, since
      same_group's same-version test is only a proxy for a lockstep bump.
    - "wrong_name": the header's name segment (see header_name_segment) isn't
      exactly "<parent> - <image-basename>" (see path_display_name). Exact equality,
      because one sidecar name can be a prefix of another.

    Primary images (see is_primary_image_path) are exempt. Unresolvable entries
    are skipped (reported elsewhere), as are paths with no owning dependency
    (e.g. "keycloak", "global"): with no parent, the sidecar shape doesn't apply."""
    problems: list[tuple[str, str, str]] = []
    for entry, line_idx in zip(manifest.entries, manifest.entry_line_indices, strict=True):
        path = resolve_entry_image_path(entry["name"], resolution.current_paths.keys(), resolution.repo_map)
        if path is None or is_primary_image_path(path, resolution.deps):
            continue
        display_name = path_display_name(path, resolution.deps, resolution.canonical_names)
        top_line = _own_header_top_line(manifest.lines, line_idx)
        match = SIDECAR_HEADER_RE.match(top_line) if top_line is not None else None
        if match is None:
            problems.append((entry["name"], display_name, "missing"))
        elif normalize_name(header_name_segment(match.group("text"))) != normalize_name(display_name):
            problems.append((entry["name"], display_name, "wrong_name"))
    return problems


def _images_manifest_groups(manifest: ParsedManifest, resolution: EntryResolution) -> list[ManifestGroup]:
    """[(indices, path, display_name), ...] per group of consecutive entries sharing one comment.

    In current manifest order; path/display_name come from the group's first
    entry (raw name if unresolvable). Shared by the sorter and the out-of-order
    check so both agree on what a group is."""
    n = len(manifest.entries)

    def same_group(entry_a: ManifestEntry, entry_b: ManifestEntry) -> bool:
        return images_manifest_entries_share_group(entry_a, entry_b, resolution.current_paths, resolution.repo_map)

    comment_idx_for = [
        find_grouped_preceding_comment_line(
            manifest.lines, manifest.entries, manifest.entry_line_indices, i, same_group
        )
        for i in range(n)
    ]
    index_groups: list[list[int]] = []
    for i in range(n):
        if i > 0 and comment_idx_for[i] is not None and comment_idx_for[i] == comment_idx_for[i - 1]:
            index_groups[-1].append(i)
        else:
            index_groups.append([i])

    groups: list[ManifestGroup] = []
    for indices in index_groups:
        path = resolve_entry_image_path(
            manifest.entries[indices[0]]["name"], resolution.current_paths.keys(), resolution.repo_map
        )
        name = (
            path_display_name(path, resolution.deps, resolution.canonical_names)
            if path
            else manifest.entries[indices[0]]["name"]
        )
        groups.append((indices, path, name))
    return groups


def _group_order_keys(
    groups: list[ManifestGroup], deps: list[ChartDependency], key_order: list[str], values: YamlMapping | None
) -> list[tuple[int, ...]]:
    """path_order_key of each group's path: the sorter orders by it and the checker compares it."""
    return [path_order_key(path, deps, key_order, values) for _indices, path, _name in groups]


def find_images_manifest_out_of_order_names(
    manifest: ParsedManifest, resolution: EntryResolution, key_order: list[str], values: YamlMapping | None = None
) -> list[tuple[str, str]]:
    """Every adjacent (name_a, name_b) group pair whose path_order_key order is inverted.

    Without values, non-primary entries under the same top-level key tie and are
    never flagged."""
    groups = _images_manifest_groups(manifest, resolution)
    keys = _group_order_keys(groups, resolution.deps, key_order, values)
    return [
        (group_a[2], group_b[2])
        for (group_a, key_a), (group_b, key_b) in pairwise(zip(groups, keys, strict=True))
        if key_b < key_a
    ]


def _collapse_group_internal_blank_lines(group_text: str) -> str:
    """Drop blank lines between entries in group_text, keeping its trailing blank line(s)."""
    lines = group_text.splitlines(keepends=True)
    last_content = len(lines)
    while last_content > 0 and lines[last_content - 1].strip() == "":
        last_content -= 1
    body = [line for line in lines[:last_content] if line.strip() != ""]
    return "".join(body + lines[last_content:])


def _images_manifest_sorted_groups(
    manifest: ParsedManifest, context: ManifestSortContext
) -> tuple[list[ManifestGroup], list[int]]:
    """(groups, order): the groups and the permutation sort_images_manifest_entries applies.

    current_paths includes the global.images anchors; without them a shared base
    image entry (e.g. "curlimages/curl") can't resolve and sorts last instead of
    under "global"."""
    current_paths = chart_image_paths(context.values, context.deps)
    resolution = EntryResolution(context.deps, current_paths, context.repo_map, context.canonical_names)
    groups = _images_manifest_groups(manifest, resolution)
    keys = _group_order_keys(groups, context.deps, values_key_order(context.values), context.values)
    return groups, sorted(range(len(groups)), key=lambda gi: keys[gi])


def _parsed_manifest_from_text(text: str) -> tuple[ParsedManifest | None, bool]:
    """(ParsedManifest, True), or (None, False) if text isn't a valid manifest list or has < 2 entries."""
    lines = text.splitlines(keepends=True)
    entries = try_parse_images_manifest(text)
    if entries is None:
        return None, False

    entry_line_indices = [i for i, line in enumerate(lines) if re.match(r"^-\s*name:", line)]
    n = min(len(entries), len(entry_line_indices))
    entries, entry_line_indices = entries[:n], entry_line_indices[:n]
    if n < 2:
        return None, False
    return ParsedManifest(entries, entry_line_indices, lines), True


def _positioned_groups(
    text: str, context: ManifestSortContext
) -> tuple[ParsedManifest, list[tuple[ManifestGroup, int]]]:
    """(manifest, [(group, 0-based position after sorting)]) in manifest order; no groups if invalid or < 2 entries."""
    manifest, ok = _parsed_manifest_from_text(text)
    if not ok or manifest is None:
        return ParsedManifest([], [], []), []
    groups, order = _images_manifest_sorted_groups(manifest, context)
    position_of_group = {orig_i: slot for slot, orig_i in enumerate(order)}
    return manifest, [(group, position_of_group[i]) for i, group in enumerate(groups)]


def images_manifest_entry_positions(text: str, context: ManifestSortContext) -> dict[str, int]:
    """{entry_name: 0-based final position} after sort_images_manifest_entries' group reordering.

    Lets callers mirror the entry order instead of fuzzy text matching. Entries
    in one group share its position. {} if invalid or fewer than 2 entries."""
    manifest, positioned = _positioned_groups(text, context)
    return {
        manifest.entries[entry_index]["name"]: position
        for (indices, _path, _name), position in positioned
        for entry_index in indices
    }


def images_manifest_display_name_positions(text: str, context: ManifestSortContext) -> dict[str, int]:
    """{display_name: 0-based final position}, like images_manifest_entry_positions but keyed by group display name.

    For exact-prefix matching of "# Changes:" items, which the tooling writes
    as f"{name} {old} -> {new}." with this display name; fuzzy basename matching
    fails where alias and image basename differ (e.g. "kiss" vs "kiss-frontend").
    Groups sharing a display name are adjacent; the lowest position wins.
    {} if invalid or fewer than 2 entries."""
    positions: dict[str, int] = {}
    for (_indices, _path, name), position in _positioned_groups(text, context)[1]:
        positions[name] = min(position, positions.get(name, position))
    return positions


def match_changes_item_display_name(rest: str, names: Iterable[str]) -> str | None:
    """The longest of `names` that rest names (see changes_item_names), or None.

    Exact: a hand-written item that names no display name first matches
    nothing. Longest wins so a sidecar ("keycloak-operator - postgres") beats
    its primary's shorter prefix. Shared by fixer and checker, for both
    manifest display names and upgrade-doc row names."""
    best: str | None = None
    for name in names:
        if changes_item_names(rest, name) and (best is None or len(name) > len(best)):
            best = name
    return best


def changes_item_order_keys(rests: Iterable[str], display_name_positions: Mapping[str, int]) -> list[int]:
    """Each "# Changes:" item's sort key: the entry position of the display name it names.

    The sorter and the checker both order by this. An item naming no display
    name (hand-written prose) sorts after every real one; there is no fuzzy
    fallback, which can misplace an item by a word it merely mentions.
    """
    last = max(display_name_positions.values(), default=-1) + 1
    return [
        display_name_positions[name]
        if (name := match_changes_item_display_name(rest, display_name_positions))
        else last
        for rest in rests
    ]


def _group_texts_and_components(
    lines: list[str], groups: list[ManifestGroup], starts: list[int]
) -> tuple[list[str], list[str | None]]:
    """(per_group_texts, components): each group's text span and its top-level component.

    A multi-entry group's internal blank lines are collapsed here."""
    ends = [*starts[1:], len(lines)]
    original_texts = ["".join(lines[s:e]) for s, e in zip(starts, ends, strict=True)]
    # The cross-group merge only sees whole groups, so collapse within a group here.
    per_group_texts = [
        _collapse_group_internal_blank_lines(t) if len(indices) > 1 else t
        for (indices, _, _), t in zip(groups, original_texts, strict=True)
    ]
    components = [path[0] if path else None for _, path, _ in groups]
    return per_group_texts, components


def _merge_ordered_groups(per_group_texts: list[str], components: list[str | None], order: list[int]) -> list[str]:
    """Merge runs of consecutive same-component groups in order into one text block each.

    Blank lines within a run are collapsed; exactly one separates runs. Groups
    with an unresolved (None) component never merge."""
    ordered_texts = [per_group_texts[i] for i in order]
    ordered_components = [components[i] for i in order]

    merged_texts: list[str] = []
    run_start = 0
    for i in range(1, len(ordered_texts) + 1):
        at_end = i == len(ordered_texts)
        if at_end or ordered_components[i] is None or ordered_components[i] != ordered_components[run_start]:
            run_text = "".join(ordered_texts[run_start:i])
            run_text = _collapse_group_internal_blank_lines(run_text) if i - run_start > 1 else run_text
            if not at_end:
                # Exactly one blank line: spans never include a leading one,
                # so a missing separator must be added here.
                run_text = run_text.rstrip("\n") + "\n\n"
            merged_texts.append(run_text)
            run_start = i
    return merged_texts


def _sorted_manifest_text(
    lines: list[str], entry_line_indices: list[int], groups: list[ManifestGroup], order: list[int]
) -> str:
    """The manifest text with order applied to groups, keeping the leading prefix."""
    starts = [images_manifest_block_start(lines, entry_line_indices[indices[0]]) for indices, _, _ in groups]
    per_group_texts, components = _group_texts_and_components(lines, groups, starts)
    merged_texts = _merge_ordered_groups(per_group_texts, components, order)
    prefix = "".join(lines[: starts[0]])
    return prefix + "".join(merged_texts)


def sort_images_manifest_entries(text: str, context: ManifestSortContext) -> tuple[str, list[tuple[str, int, int]]]:
    """Reorder manifest entry groups into values.yaml order, moving each group as one unit.

    Also formats, whether or not anything moved: blank lines between groups of
    the same top-level component are collapsed (a component and its sidecars
    read as one block), and exactly one blank line separates different
    components. A group's span never includes a leading blank line, so a missing
    separator must be inserted, not just excess collapsed.

    Returns (new_text, moved), moved being [(display_name, old_pos, new_pos)]
    (1-based) for groups that moved; new_text may differ with moved empty when
    only blank lines changed. (text, []) if nothing changed, the text isn't a
    valid manifest or has fewer than 2 entries."""
    manifest, ok = _parsed_manifest_from_text(text)
    if not ok or manifest is None:
        return text, []

    groups, order = _images_manifest_sorted_groups(manifest, context)
    moved = [(groups[i][2], i + 1, slot + 1) for slot, i in enumerate(order) if i != slot]

    new_text = _sorted_manifest_text(manifest.lines, manifest.entry_line_indices, groups, order)
    if new_text == text:
        return text, []
    return new_text, moved
