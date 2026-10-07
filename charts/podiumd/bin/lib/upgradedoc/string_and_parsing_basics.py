"""Upgrade-doc text primitives: name/version normalization, word-boundary name matching, table parsing."""

import re

from collections.abc import Iterable
from collections.abc import Mapping
from collections.abc import Sequence
from typing import Literal
from typing import TypedDict
from typing import TypeVar

from lib.chart.chart_yaml import ChartDependency
from lib.chart.registered_paths import native_components
from lib.chart.values_tree_primitives import values_key_of

COMPONENT_VERSIONS_HEADING_RE = re.compile(r"^##\s+Component versions\b")
FENCE_LINE_RE = re.compile(r"^\s*```")

# A sidecar/shared image by values-tree path, or a dependency/native component by values key.
ComponentRef = tuple[Literal["sidecar"], tuple[str, ...]] | tuple[Literal["dep"], str]


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


def normalize_version(v: str | None):
    """`v` without a leading "v"/"V", so doc and Chart.yaml versions compare equal; falsy passes through."""
    return v.lstrip("vV") if v else v


def normalize_name(s: str):
    """`s` lowercased with non-alphanumerics stripped: the key for case/punctuation-insensitive matching."""
    return re.sub(r"[^a-z0-9]", "", s.lower())


def words_of(s: str):
    """`s` lowercased and split into alphanumeric words.

    "ZGW Office Add-in (frontend)" -> ["zgw", "office", "add", "in", "frontend"]."""
    return [w for w in re.split(r"[^a-zA-Z0-9]+", s.lower()) if w]


# The two extractors differ in the arrow side their first pattern matches;
# one function with a side argument would read worse than the pair.
# jscpd:ignore-start
def extract_target_version(cell: str) -> str | None:
    """Pull the target (right-hand) version out of a markdown table cell like
    "5.0.2 → 5.4.3" or "1.0.297 (unchanged)" or "`0.0.92`"."""
    cell = cell.strip()
    m = re.search(r"(?:→|->)\s*`?([A-Za-z0-9][\w.\-]*)", cell)
    if m:
        return m.group(1)
    m = re.match(r"`?([A-Za-z0-9][\w.\-]*)", cell)
    return m.group(1) if m else None


def extract_source_version(cell: str) -> str | None:
    """Pull the source (left-hand) version out of the same kind of cell —
    equal to the target when the cell has no arrow (e.g. "1.0.297 (unchanged)")."""
    cell = cell.strip()
    m = re.search(r"`?([A-Za-z0-9][\w.\-]*)`?\s*(?:→|->)", cell)
    if m:
        return m.group(1)
    m = re.match(r"`?([A-Za-z0-9][\w.\-]*)", cell)
    return m.group(1) if m else None


# jscpd:ignore-end


def _table_cell_source_version(cell: str) -> str | None:
    """extract_source_version for a table cell; None for "<version> (new)", which has no source."""
    return None if cell.strip().endswith("(new)") else extract_source_version(cell)


def table_cells(line: str) -> list[str]:
    """The stripped cells of a Markdown table row."""
    return [c.strip() for c in line.strip().strip("|").split("|")]


def set_row_cells(lines: list[str], row: TableRow, app_cell: str | None, chart_cell: str | None) -> list[str] | None:
    """Write `row`'s App version and Helm chart cells into `lines`; None leaves a cell as it is.

    Returns the row's new cells when the line changed, else None. The other
    cells (name, notes) are kept.
    """
    line = lines[row["line_index"]]
    old_cells = table_cells(line)
    cells = [*old_cells]
    if app_cell is not None:
        cells[1] = app_cell
    if chart_cell is not None:
        cells[2] = chart_cell
    if cells == old_cells:
        return None
    lines[row["line_index"]] = "| " + " | ".join(cells) + " |" + ("\n" if line.endswith("\n") else "")
    return cells


def parse_upgrade_doc_rows(text: str) -> list[TableRow]:
    """Every row of the "## Component versions" table, with its 0-based `line_index`.

    Scoped to that section (up to the next "## "), so other pipe-tables in the doc are never
    read as component rows. [] without the heading."""
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if COMPONENT_VERSIONS_HEADING_RE.match(line.strip()):
            start = i + 1
            break
    if start is None:
        return []

    end = len(lines)
    for i in range(start, len(lines)):
        if re.match(r"^##\s+\S", lines[i]):
            end = i
            break

    rows: list[TableRow] = []
    for i in range(start, end):
        line = lines[i]
        if not line.strip().startswith("|"):
            continue
        cells = table_cells(line)
        if len(cells) < 3 or cells[0].lower() == "component":
            continue
        if all(re.match(r"^:?-+:?$", c) for c in cells):
            continue
        rows.append(
            {
                "line_index": i,
                "name": cells[0],
                "app_source": _table_cell_source_version(cells[1]),
                "app": extract_target_version(cells[1]),
                "chart_source": _table_cell_source_version(cells[2]),
                "chart": extract_target_version(cells[2]),
            }
        )
    return rows


def _word_aligned_spans(text: str) -> set[str]:
    """Every contiguous run of words in `text`, concatenated and normalized.

    "ZGW Office Add-in (frontend)" -> {"zgw", "zgwoffice", ..., "frontend"}. Membership matches
    whole words only: alias "mi" is a raw substring of "ensurePodiumdAdminUser" but not a span."""
    words = words_of(text)
    spans: set[str] = set()
    for i in range(len(words)):
        acc = ""
        for j in range(i, len(words)):
            acc += words[j]
            spans.add(acc)
    return spans


def word_contains(text: str, name: str) -> bool:
    """Whether `name`, normalized, is a run of whole words of `text`
    (see _word_aligned_spans): "Open Inwoner platform" contains
    "openinwoner", but "ensurePodiumdAdminUser" does not contain "mi"."""
    norm = normalize_name(name)
    return bool(norm) and norm in _word_aligned_spans(text)


def text_names(text: str, name: str) -> bool:
    """Whether `text` (a table row's Name cell, a "### ..." heading or a
    "# Changes:" item) names `name`. A plain name matches at word
    boundaries (_word_aligned_spans), so "mi" never matches "AdminUser".
    A canonical "<key> - <image-basename>" sidecar name (lib.chart.canonical_
    sidecar_row_names) only matches text that starts with exactly its
    words, followed by nothing or a version: "zac - postgres" never
    matches "zac - postgres-exporter 1.0", and a plain name never
    matches a sidecar's text, nor the reverse."""
    if " - " not in text and " - " not in name:
        return word_contains(text, name)
    if " - " not in text or " - " not in name:
        return False
    name_words, words = words_of(name), words_of(text)
    rest = words[len(name_words) :]
    return words[: len(name_words)] == name_words and (not rest or re.match(r"v?\d", rest[0]) is not None)


_CHANGES_ITEM_AFTER_NAME_RE = re.compile(r"v?\d|->|→|\(")


def changes_item_names(rest: str, name: str) -> bool:
    """Whether "# Changes:" item text `rest` names exactly `name`.

    It is `name` (ignoring case), optionally followed by a space and a version, an arrow or a
    "(" remark. Exact, not a word search: "nginx" never matches "nginx-unprivileged -> 1.31.3",
    and "zac" never matches "zac - postgres 17.1". Shared by writers, check and fixer."""
    text, prefix = rest.strip().lower(), name.strip().lower()
    if not prefix:
        return False
    if text == prefix:
        return True
    return text.startswith(prefix + " ") and _CHANGES_ITEM_AFTER_NAME_RE.match(text, len(prefix) + 1) is not None


ItemT = TypeVar("ItemT")


def match_dependency(text: str, deps: list[ChartDependency]):
    """Match a doc's free-form component name against Chart.yaml dependency names/aliases.

    Case/punctuation-insensitive, at word boundaries only (see _word_aligned_spans)."""
    return best_name_match(text, ((dep, (dep["name"], dep.get("alias"))) for dep in deps))


def best_name_match(text: str, candidates: Iterable[tuple[ItemT, Iterable[str | None]]]) -> ItemT | None:
    """The item whose names give the longest word-aligned match in `text`, or None.

    `candidates` pairs each item with its names; None names are skipped."""
    spans = _word_aligned_spans(text)
    best_item, best_norm = None, None
    for item, names in candidates:
        for candidate in filter(None, names):
            norm_c = normalize_name(candidate)
            if norm_c and norm_c in spans and (best_norm is None or len(norm_c) > len(best_norm)):
                best_item, best_norm = item, norm_c
    return best_item


def match_native_component(text: str, native_component_names: set[str] | frozenset[str]):
    """match_dependency's word-boundary match against native component names.

    Separate from match_dependency because callers differ on whether native components
    should match. Takes resolved names, not chart_dir, for callers without one."""
    spans = _word_aligned_spans(text)
    best_key, best_norm = None, None
    for key in native_component_names:
        norm = normalize_name(key)
        if norm and norm in spans and (best_norm is None or len(norm) > len(best_norm)):
            best_key, best_norm = key, norm
    return best_key


def match_canonical_sidecar_name(
    text: str, canonical_names: Mapping[str, tuple[str, ...]] | None
) -> tuple[str, ...] | None:
    """The values-tree path of the one canonical sidecar/shared-image
    name (lib.chart.canonical_sidecar_row_names) that `text` names: an
    exact key of canonical_names (a table row's bare name), else the
    only name text_names finds in it (a "### ..." heading, whose name is
    followed by a version). None when no name or more than one name
    matches, or when canonical_names is None."""
    if canonical_names is None:
        return None
    exact = canonical_names.get(text)
    if exact is not None:
        return exact
    paths = {path for name, path in canonical_names.items() if text_names(text, name)}
    return paths.pop() if len(paths) == 1 else None


def match_dependency_excluding_sidecar_names(text: str, deps: list[ChartDependency]):
    """match_dependency, but None when `text` contains " - " (the canonical sidecar delimiter).

    Otherwise "redis-operator - redis" would match the redis-operator dependency. Use it
    wherever a match must be a real Chart.yaml component; not in component_order_key, which
    wants a sidecar row to sort near its owning dependency."""
    return None if " - " in text else match_dependency(text, deps)


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
    candidates_by_key = [
        (cand, values_key_of(dep)) for dep in deps for cand in filter(None, [dep.get("name"), dep.get("alias")])
    ]
    candidates_by_key += [(key, key) for key in native_components()]
    for candidate, key in candidates_by_key:
        norm_c = normalize_name(candidate)
        if not norm_c:
            continue
        for start in range(len(words)):
            acc = ""
            for end in range(start, len(words)):
                acc += words[end]
                if len(acc) > len(norm_c):
                    break
                if acc == norm_c:
                    matches.append((start, end + 1, key))
                    break
    kept = [
        key
        for start, end, key in matches
        if not any(
            o_start <= start and end <= o_end and (o_start, o_end) != (start, end) for o_start, o_end, _ in matches
        )
    ]
    return {("dep", key) for key in kept}


def match_located_line(pattern: re.Pattern[str], line: str) -> re.Match[str]:
    """pattern.match(line) for a line the caller already located with the
    same pattern. Raises ValueError if it does not match: that is a bug in
    the caller, not a problem in the document."""
    m = pattern.match(line)
    if m is None:
        msg = f"line does not match {pattern.pattern!r}: {line!r}"
        raise ValueError(msg)
    return m


def fenced_line_flags(lines: Sequence[str]) -> list[bool]:
    """Per line: True for a ``` fence line or a line inside a fenced code block."""
    flags: list[bool] = []
    in_fence = False
    for line in lines:
        is_fence = bool(FENCE_LINE_RE.match(line))
        flags.append(in_fence or is_fence)
        if is_fence:
            in_fence = not in_fence
    return flags
