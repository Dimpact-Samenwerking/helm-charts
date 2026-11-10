"""Upgrade-doc text primitives: name/version normalization, word-boundary name matching, table and heading parsing."""

import re

from collections.abc import Iterable
from collections.abc import Iterator
from collections.abc import Mapping
from collections.abc import Sequence
from itertools import combinations
from typing import Literal
from typing import NamedTuple
from typing import TypedDict

from lib.chart.chart_yaml import ChartDependency
from lib.chart.registered_paths import native_components
from lib.chart.values_tree_primitives import dependency_name_and_alias
from lib.chart.values_tree_primitives import values_key_of

# Matched against a "##" heading's text (markdown_headings), as every writer and check does.
COMPONENT_VERSIONS_HEADING_RE = re.compile(r"^Component versions\b")
FENCE_LINE_RE = re.compile(r"^\s*(?P<fence>`{3,}|~{3,})")
# Optional closing marks ("## Checklist ##") are not part of the text.
_HEADING_RE = re.compile(r"^(?P<marks>#{1,6})\s+(?P<text>.*?)(?:\s+#+)?\s*$")

type SidecarRef = tuple[Literal["sidecar"], tuple[str, ...]]
type DependencyRef = tuple[Literal["dep"], str]
# A sidecar/shared image by values-tree path, or a dependency/native component by values key.
type ComponentRef = SidecarRef | DependencyRef


class VersionRow(TypedDict):
    """One component's version change as a document states it: the
    Component-versions table row (see TableRow) or a "# Changes:" item
    (parse_changes_block). Each version is None when its cell has none; a
    source is also None for a "<version> (new)" table cell."""

    name: str
    app_source: str | None
    app: str | None
    chart_source: str | None
    chart: str | None


class TableRow(VersionRow):
    """A Component-versions table row (parse_upgrade_doc_rows), with its
    0-based line in the document."""

    line_index: int


def normalize_version(version: str | None):
    """`version` without a leading "v"/"V", so doc and Chart.yaml versions compare equal; falsy passes through."""
    return version.lstrip("vV") if version else version


def normalize_name(text: str):
    """`text` lowercased with non-alphanumerics stripped: the key for case/punctuation-insensitive matching."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


def words_of(text: str):
    """`text` lowercased and split into alphanumeric words.

    "ZGW Office Add-in (frontend)" -> ["zgw", "office", "add", "in", "frontend"]."""
    return [word for word in re.split(r"[^a-zA-Z0-9]+", text.lower()) if word]


# The two extractors differ in the arrow side their first pattern matches;
# one function with a side argument would read worse than the pair.
# jscpd:ignore-start
def extract_target_version(cell: str) -> str | None:
    """Pull the target (right-hand) version out of a markdown table cell like
    "5.0.2 → 5.4.3" or "1.0.297 (unchanged)" or "`0.0.92`". None for "0.20.0 → -"
    (the chart went away: a native component that was a dependency)."""
    cell = cell.strip()
    version_match = re.search(r"(?:→|->)\s*`?([A-Za-z0-9][\w.\-]*|-(?![\w.]))", cell)
    if version_match:
        return None if version_match.group(1) == "-" else version_match.group(1)
    version_match = re.match(r"`?([A-Za-z0-9][\w.\-]*)", cell)
    return version_match.group(1) if version_match else None


def extract_source_version(cell: str) -> str | None:
    """Pull the source (left-hand) version out of the same kind of cell —
    equal to the target when the cell has no arrow (e.g. "1.0.297 (unchanged)")."""
    cell = cell.strip()
    version_match = re.search(r"`?([A-Za-z0-9][\w.\-]*)`?\s*(?:→|->)", cell)
    if version_match:
        return version_match.group(1)
    version_match = re.match(r"`?([A-Za-z0-9][\w.\-]*)", cell)
    return version_match.group(1) if version_match else None


# jscpd:ignore-end


def _table_cell_source_version(cell: str) -> str | None:
    """extract_source_version for a table cell; None for "<version> (new)", which has no source."""
    return None if cell.strip().endswith("(new)") else extract_source_version(cell)


_SEPARATOR_CELL_RE = re.compile(r"^:?-+:?$")


def table_cells(line: str) -> list[str]:
    """The stripped cells of a Markdown table row."""
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def is_table_separator(line: str) -> bool:
    """Whether `line` is a Markdown table's "| --- | :-: |" separator row."""
    if not line.strip().startswith("|"):
        return False
    return all(_SEPARATOR_CELL_RE.match(cell) for cell in table_cells(line))


def table_data_cells(line: str) -> list[str] | None:
    """The cells of a Markdown table row; None for a separator or a line that is no table row."""
    if not line.strip().startswith("|") or is_table_separator(line):
        return None
    return table_cells(line)


def set_row_cells(
    lines: list[str],
    row: TableRow,
    app_cell: str | None,
    chart_cell: str | None,
) -> list[str] | None:
    """Write `row`'s App version and Helm chart cells into `lines`; None leaves a cell as it is.

    Returns the row's new cells when the line changed, else None. The other
    cells (name, notes) are kept.
    """
    line = lines[row["line_index"]]
    old_cells = table_cells(line)
    cells = list(old_cells)
    if app_cell is not None:
        cells[1] = app_cell
    if chart_cell is not None:
        cells[2] = chart_cell
    if cells == old_cells:
        return None
    ending = "\n" if line.endswith("\n") else ""
    row_text = " | ".join(cells)
    lines[row["line_index"]] = f"| {row_text} |{ending}"
    return cells


# Name, App version and Helm chart; fewer cells is not a component row.
_MIN_TABLE_ROW_CELLS = 3


def parse_upgrade_doc_rows(text: str) -> list[TableRow]:
    """Every row of the "## Component versions" table, with its 0-based `line_index`.

    Scoped to that section (up to the next "## "), so other pipe-tables in the doc are never
    read as component rows. [] without the heading."""
    lines = text.splitlines()
    start, end = versions_section_bounds(lines)
    if start is None:
        return []
    start += 1

    rows: list[TableRow] = []
    for line_index in range(start, end):
        cells = _component_row_cells(lines[line_index])
        if cells is None:
            continue
        rows.append(
            {
                "line_index": line_index,
                "name": cells[0],
                "app_source": _table_cell_source_version(cells[1]),
                "app": extract_target_version(cells[1]),
                "chart_source": _table_cell_source_version(cells[2]),
                "chart": extract_target_version(cells[2]),
            }
        )
    return rows


def _component_row_cells(line: str) -> list[str] | None:
    """The cells of a component table row; None for a non-table, header or separator line."""
    cells = table_data_cells(line)
    if cells is None or len(cells) < _MIN_TABLE_ROW_CELLS or cells[0].lower() == "component":
        return None
    return cells


def word_aligned_spans(text: str) -> set[str]:
    """Every contiguous run of words in `text`, concatenated and normalized.

    "ZGW Office Add-in (frontend)" -> {"zgw", "zgwoffice", ..., "frontend"}. Membership matches
    whole words only: alias "mi" is a raw substring of "ensurePodiumdAdminUser" but not a span."""
    return {run for _, _, run in _word_runs(words_of(text))}


def _word_runs(words: Sequence[str]) -> Iterator[tuple[int, int, str]]:
    """(start, end exclusive, concatenation) of every contiguous run of `words`, by start then end."""
    for start, end in combinations(range(len(words) + 1), 2):
        yield start, end, "".join(words[start:end])


def has_word_run(text: str, name: str) -> bool:
    """Whether `name`, normalized, is a run of whole words of `text`
    (see word_aligned_spans): "Open Inwoner platform" contains
    "openinwoner", but "ensurePodiumdAdminUser" does not contain "mi"."""
    norm = normalize_name(name)
    return bool(norm) and norm in word_aligned_spans(text)


def is_named_by_text(text: str, name: str) -> bool:
    """Whether `text` (a table row's Name cell, a "### ..." heading or a
    "# Changes:" item) names `name`. A plain name matches at word
    boundaries (word_aligned_spans), so "mi" never matches "AdminUser".
    A canonical "<key> - <image-basename>" sidecar name (lib.chart.canonical_
    sidecar_row_names) only matches text that starts with exactly its
    words, followed by nothing or a version: "zac - postgres" never
    matches "zac - postgres-exporter 1.0", and a plain name never
    matches a sidecar's text, nor the reverse."""
    if " - " not in text and " - " not in name:
        return has_word_run(text, name)
    if " - " not in text or " - " not in name:
        return False
    name_words, words = words_of(name), words_of(text)
    rest = words[len(name_words) :]
    rest_is_version = not rest or re.match(r"v?\d", rest[0]) is not None
    return words[: len(name_words)] == name_words and rest_is_version


_CHANGES_ITEM_AFTER_NAME_RE = re.compile(r"v?\d|->|→|\(")


def is_named_by_changes_item(rest: str, name: str) -> bool:
    """Whether "# Changes:" item text `rest` names exactly `name`.

    It is `name` (ignoring case), optionally followed by a space and a version, an arrow or a
    "(" remark. Exact, not a word search: "nginx" never matches "nginx-unprivileged -> 1.31.3",
    and "zac" never matches "zac - postgres 17.1". Shared by writers, check and fixer."""
    text, prefix = rest.strip().lower(), name.strip().lower()
    if not prefix:
        return False
    if text == prefix:
        return True
    after_name = _CHANGES_ITEM_AFTER_NAME_RE.match(text, len(prefix) + 1)
    return text.startswith(f"{prefix} ") and after_name is not None


# An item paired with the names it may be called by.
type NamedCandidate[CandidateT] = tuple[CandidateT, Iterable[str | None]]


def best_name_match[ItemT](text: str, candidates: Iterable[NamedCandidate[ItemT]]) -> ItemT | None:
    """The item whose names give the longest word-aligned match in `text`, or None.

    `candidates` pairs each item with its names; None names are skipped."""
    spans = word_aligned_spans(text)
    best_item, best_norm = None, None
    for item, names in candidates:
        for candidate in filter(None, names):
            norm_c = normalize_name(candidate)
            if norm_c and norm_c in spans and (best_norm is None or len(norm_c) > len(best_norm)):
                best_item, best_norm = item, norm_c
    return best_item


def match_component(
    text: str, deps: list[ChartDependency], native_component_names: set[str] | frozenset[str]
) -> ChartDependency | str | None:
    """The dependency, or native component key, that `text` names, or None.

    First an exact match (case/punctuation-insensitive) on a dependency name or
    alias or a native component key: of the whole text, or of the first key of a
    values path ("kiss-eck.eck-kibana.image"). So "kiss-eck" is the native, not
    the "kiss" alias of another dependency. Otherwise the longest
    match at word boundaries (see word_aligned_spans): dependencies first, then
    native components. Dependencies are skipped when `text` contains " - " (the
    canonical sidecar delimiter), so "redis-operator - redis" is not the
    redis-operator dependency. Not for component_order_key, which wants a sidecar
    row to sort near its owning dependency."""
    named_deps: list[ChartDependency] = [] if " - " in text else deps
    dep_candidates = [(dep, dependency_name_and_alias(dep)) for dep in named_deps]
    natives = sorted(native_component_names)
    is_values_path = "." in text and not any(char.isspace() for char in text)
    norm = normalize_name(text.split(".", 1)[0] if is_values_path else text)
    for dep, names in dep_candidates:
        if any(name and normalize_name(name) == norm for name in names):
            return dep
    exact_native = next((key for key in natives if normalize_name(key) == norm), None)
    if exact_native is not None:
        return exact_native
    return best_name_match(text, dep_candidates) or best_name_match(text, ((key, (key,)) for key in natives))


def match_canonical_sidecar_name(
    text: str, canonical_names: Mapping[str, tuple[str, ...]] | None
) -> tuple[str, ...] | None:
    """The values-tree path of the one canonical sidecar/shared-image
    name (lib.chart.canonical_sidecar_row_names) that `text` names: an
    exact key of canonical_names (a table row's bare name), else the
    only name is_named_by_text finds in it (a "### ..." heading, whose name is
    followed by a version). None when no name or more than one name
    matches, or when canonical_names is None."""
    if canonical_names is None:
        return None
    exact = canonical_names.get(text)
    if exact is not None:
        return exact
    paths = {path for name, path in canonical_names.items() if is_named_by_text(text, name)}
    return paths.pop() if len(paths) == 1 else None


def changes_heading_identities(
    heading: str, deps: list[ChartDependency], canonical_names: Mapping[str, tuple[str, ...]] | None
) -> set[ComponentRef]:
    """Component identities named anywhere in a "### ..." Changes heading's text.

    The heading is never split on separators: any wording may join two components. A
    canonical sidecar match is returned alone (it necessarily contains its parent's name).
    Otherwise every dependency or native component matching a contiguous word range is
    collected ("### ECK Operator ... + ECK Stack (kiss-eck) ..." gives both). A match
    contained in a longer match is dropped, so "kiss-eck" does not also count as KISS's "kiss"
    alias. A heading containing " - " that matches no canonical sidecar returns empty, so
    "### openbao - openbao 2.5.5" is not credited to the openbao dependency."""
    sidecar_path = match_canonical_sidecar_name(heading, canonical_names)
    if sidecar_path is not None:
        return {("sidecar", sidecar_path)}
    if " - " in heading:
        return set()
    words = words_of(heading)
    matches: list[tuple[int, int, str]] = []  # end exclusive
    named_deps = [(dep, name) for dep in deps for name in dependency_name_and_alias(dep) if name]
    candidates_by_key = [(name, values_key_of(dep)) for dep, name in named_deps]
    candidates_by_key += [(key, key) for key in native_components()]
    runs = list(_word_runs(words))
    for candidate, key in candidates_by_key:
        norm_c = normalize_name(candidate)
        matches += [(start, end, key) for start, end, run in runs if norm_c and run == norm_c]
    kept = [key for start, end, key in matches if not _is_inside_longer_match(start, end, matches)]
    return {("dep", key) for key in kept}


def single_heading_identity(
    heading: str, deps: list[ChartDependency], canonical_names: Mapping[str, tuple[str, ...]] | None
) -> ComponentRef | None:
    """The one component a "### ..." heading names (changes_heading_identities), or None for none or several."""
    idents = changes_heading_identities(heading, deps, canonical_names)
    return next(iter(idents)) if len(idents) == 1 else None


def _is_inside_longer_match(start: int, end: int, matches: Sequence[tuple[int, int, str]]) -> bool:
    """True when another match's word range contains [start, end)."""
    others = [(o_start, o_end) for o_start, o_end, _ in matches if (o_start, o_end) != (start, end)]
    return any(o_start <= start and end <= o_end for o_start, o_end in others)


def match_located_line(pattern: re.Pattern[str], line: str) -> re.Match[str]:
    """pattern.match(line) for a line the caller already located with the
    same pattern. Raises ValueError if it does not match: that is a bug in
    the caller, not a problem in the document."""
    matched = pattern.match(line)
    if matched is None:
        msg = f"line does not match {pattern.pattern!r}: {line!r}"
        raise ValueError(msg)
    return matched


def fenced_line_flags(lines: Sequence[str]) -> list[bool]:
    """Per line: True for a fence line (``` or ~~~), a line inside a fenced code
    block, or a line of an HTML comment that starts a line and spans several.

    A fence closes only on a fence of its own character, at least as long."""
    flags: list[bool] = []
    fence = ""
    in_comment = False
    for line in lines:
        fence_match = FENCE_LINE_RE.match(line)
        if fence:
            flags.append(True)
            fence = _fence_after(fence, fence_match)
        elif in_comment:
            flags.append(True)
            in_comment = "-->" not in line
        else:
            fence, in_comment = _block_opened_by(line, fence_match)
            flags.append(bool(fence) or in_comment)
    return flags


def _fence_after(fence: str, fence_match: re.Match[str] | None) -> str:
    """The open fence after a line inside it: "" when the line closes it."""
    closing = fence_match["fence"] if fence_match else ""
    if closing.startswith(fence[0]) and len(closing) >= len(fence):
        return ""
    return fence


def _block_opened_by(line: str, fence_match: re.Match[str] | None) -> tuple[str, bool]:
    """(fence, in multi-line HTML comment) a line outside any block opens."""
    if fence_match:
        return fence_match["fence"], False
    return "", line.lstrip().startswith("<!--") and "-->" not in line


def heading_slug(heading: str):
    """The anchor GitHub gives a heading, which pymarkdown's MD051 checks "(#...)" links against."""
    kept = "".join(char for char in heading.lower() if char.isalnum() or char in " -_")
    return kept.replace(" ", "-")


class MarkdownHeading(NamedTuple):
    """A "#" heading: its 0-based line index, its marks ("##") and its text."""

    line: int
    marks: str
    text: str


def markdown_headings(text: str | Sequence[str]) -> list[MarkdownHeading]:
    """Each "#" heading outside fenced code blocks and HTML comments, in document order.

    Takes the text or its lines (with or without line ends); `line` indexes them.
    The one heading detection of the doc writers and checks."""
    lines = text.splitlines() if isinstance(text, str) else text
    fenced = fenced_line_flags(lines)
    return [
        MarkdownHeading(line_index, heading_match.group("marks"), heading_match.group("text"))
        for line_index, (line, in_fence) in enumerate(zip(lines, fenced, strict=True))
        if not in_fence and (heading_match := _HEADING_RE.match(line))
    ]


def next_level2_line(headings: Sequence[MarkdownHeading], start_line: int, line_count: int) -> int:
    """The line of the first "##" heading after start_line, else line_count."""
    return next(
        (heading.line for heading in headings if heading.line > start_line and heading.marks == "##"), line_count
    )


def versions_section_bounds(lines: Sequence[str]) -> tuple[int | None, int]:
    """(heading line, section end) of "## Component versions"; (None, len(lines)) if absent."""
    headings = markdown_headings(lines)
    start = next(
        (
            heading.line
            for heading in headings
            if heading.marks == "##" and COMPONENT_VERSIONS_HEADING_RE.match(heading.text)
        ),
        None,
    )
    if start is None:
        return None, len(lines)
    return start, next_level2_line(headings, start, len(lines))
