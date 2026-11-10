"""Fetch a Confluence page's storage-format body and extract its tables as plain-text grids.

Also holds the release-changes column matching used by
export-confluence-release-table.

body.storage, not body.view: tables inside a Synced Block only render as a
placeholder in body.view. Auth is HTTP Basic (email + API token); the API root
is ".../wiki/rest/api" for Cloud and ".../rest/api" for Server/DC."""

import base64
import json
import re
import sys

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from dataclasses import field
from html.parser import HTMLParser
from typing import IO
from typing import TypedDict
from typing import override
from urllib.parse import parse_qs
from urllib.parse import urlparse
from urllib.request import Request
from urllib.request import urlopen as default_urlopen

from lib.chart.values_tree_primitives import get_path
from lib.cli import network_errors
from lib.yaml_types import is_yaml_value

PAGE_ID_RE = re.compile(r"/pages/(\d+)")


def page_id_from_url(url: str) -> str:
    """The numeric content ID from a "/pages/<id>/..." or "?pageId=<id>" Confluence URL."""
    page_match = PAGE_ID_RE.search(url)
    if page_match:
        return page_match.group(1)
    query = parse_qs(urlparse(url).query)
    if "pageId" in query:
        return query["pageId"][0]
    sys.exit(f"error: could not find a page ID in {url}")


def api_base_url(url: str) -> str:
    """The REST API root: ".../wiki/rest/api" for Cloud, ".../rest/api" for Server/DC."""
    parsed = urlparse(url)
    wiki_idx = parsed.path.find("/wiki/")
    api_path = f"{parsed.path[:wiki_idx]}/wiki/rest/api" if wiki_idx != -1 else "/rest/api"
    return f"{parsed.scheme}://{parsed.netloc}{api_path}"


# urllib.request.urlopen's shape, so tests can pass a fake.
type UrlOpener = Callable[[Request], AbstractContextManager[IO[bytes]]]


def fetch_page_html(
    url: str,
    user: str,
    token: str,
    urlopen: UrlOpener = default_urlopen,
) -> str:
    """The page's body.storage.value via the REST API.

    `urlopen` is overridable for tests. Raises SystemExit on a non-http(s) URL, a
    failed request or unexpected JSON."""
    if urlparse(url).scheme not in {"http", "https"}:
        sys.exit(f"error: --url {url} must start with https://")
    page_id = page_id_from_url(url)
    api_url = f"{api_base_url(url)}/content/{page_id}?expand=body.storage"
    auth = base64.b64encode(f"{user}:{token}".encode()).decode()
    request = Request(
        api_url,
        headers={
            "Authorization": f"Basic {auth}",
            "Accept": "application/json",
        },
    )
    try:
        with network_errors("Confluence"), urlopen(request) as response:
            data: object = json.load(response)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        sys.exit(f"error: Confluence didn't answer with JSON ({error}) — check --url (a login page?)")
    value = get_path(data, "body.storage.value") if is_yaml_value(data) else None
    if not isinstance(value, str):
        sys.exit("error: response had no body.storage.value — check the URL and permissions")
    return value


HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}

# Separate adjacent blocks in a cell, else "<p>5.4.3</p><hr/><p>5.4.4</p>" reads "5.4.35.4.4".
BLOCK_SEPARATOR_TAGS = {"br", "hr", "p"}


class TableCell(TypedDict):
    """One <td>/<th>: tag, spans and whitespace-normalized text."""

    tag: str
    colspan: int
    rowspan: int
    text: str


class ReleaseColumns(TypedDict):
    """Grid column index per release-table field; None when absent."""

    first: int | None
    vendor: int | None
    used_by: int | None
    source_app: int | None
    source_helm: int | None
    target_app: int | None
    target_helm: int | None


# The rows of one <table>, each a list of its cells.
type TableRows = list[list[TableCell]]

# (heading, rows) of one extracted <table> — see extract_tables.
type ConfluenceTable = tuple[str | None, TableRows]

# (label, column indices) of one "Versie ..." header group — see find_versie_groups.
type VersieGroup = tuple[str, list[int]]


@dataclass
class _HeadingState:
    """Last closed heading text, plus the heading tag and text being read."""

    current: str | None = None
    tag: str | None = None
    text: list[str] = field(default_factory=list)


@dataclass
class _OpenCell:
    """A <td>/<th> still being read."""

    tag: str
    colspan: int
    rowspan: int
    parts: list[str] = field(default_factory=list)

    def finished(self) -> TableCell:
        """The TableCell with text joined and whitespace-normalized."""
        text = " ".join("".join(self.parts).split())
        return {"tag": self.tag, "colspan": self.colspan, "rowspan": self.rowspan, "text": text}


class _TableExtractor(HTMLParser):
    """Collect rows per top-level <table>, with the nearest preceding h1-h6 text.

    A table nested in a cell is flattened into that cell's text; _nested_depth
    keeps its closing tags from closing the outer cell early."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables: list[TableRows] = []
        self.table_headings: list[str | None] = []
        self._table_stack: list[TableRows] = []
        self._row: list[TableCell] | None = None
        self._cell: _OpenCell | None = None
        self._nested_depth: int = 0
        self._heading: _HeadingState = _HeadingState()

    @override
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        if self._cell is not None:
            if tag == "table":
                self._nested_depth += 1
            elif tag in BLOCK_SEPARATOR_TAGS and self._nested_depth == 0:
                self._cell.parts.append(" ")
            return
        if tag in HEADING_TAGS:
            self._heading.tag = tag
            self._heading.text = []
            return
        attr_map = dict(attrs)
        if tag == "table":
            self._table_stack.append([])
        elif tag == "tr" and self._table_stack:
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = _OpenCell(
                tag, _positive_int(attr_map.get("colspan"), 1), _positive_int(attr_map.get("rowspan"), 1)
            )
            self._nested_depth = 0

    @override
    def handle_endtag(self, tag: str):
        if self._cell is not None:
            if tag == "table" and self._nested_depth > 0:
                self._nested_depth -= 1
            elif tag in {"tr", "td", "th"} and self._nested_depth > 0:
                pass  # a nested table's own row/cell close — not the outer cell's
            elif tag in {"td", "th"}:
                if self._row is not None:
                    self._row.append(self._cell.finished())
                self._cell = None
            return
        if tag == self._heading.tag:
            self._heading.current = " ".join("".join(self._heading.text).split())
            self._heading.tag = None
        elif tag == "table" and self._table_stack:
            self.tables.append(self._table_stack.pop())
            self.table_headings.append(self._heading.current)
        elif tag == "tr" and self._row is not None:
            if self._table_stack:
                self._table_stack[-1].append(self._row)
            self._row = None

    @override
    def handle_data(self, data: str):
        if self._cell is not None:
            self._cell.parts.append(data)
        elif self._heading.tag is not None:
            self._heading.text.append(data)


def _positive_int(value: str | None, default: int) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def extract_tables(html_text: str) -> list[ConfluenceTable]:
    """(heading, rows) per <table> in document order; heading is the nearest preceding h1-h6, or None."""
    parser = _TableExtractor()
    parser.feed(html_text)
    return list(zip(parser.table_headings, parser.tables, strict=True))


def tables_under_headings(tables: list[ConfluenceTable], headings: list[str]) -> list[tuple[str, TableRows]]:
    """Tables whose heading matches one of `headings` (case- and whitespace-insensitive, exact)."""
    wanted = {_normalize(heading) for heading in headings}
    return [(heading, rows) for heading, rows in tables if heading and _normalize(heading) in wanted]


def expand_grid(rows: TableRows) -> list[list[str]]:
    """Rows as a rectangular grid of strings, with colspan/rowspan expanded; gaps become ""."""
    grid: list[list[str]] = []
    carry: dict[int, tuple[str, int]] = {}  # column -> (text, remaining_rows_including_this_one)
    for row in rows:
        grid_row: list[str] = []
        col = 0
        cell_iter = iter(row)
        current_cell = next(cell_iter, None)
        while current_cell is not None or any(carried_col >= col for carried_col in carry):
            if col in carry:
                text, remaining = carry[col]
                grid_row.append(text)
                if remaining <= 1:
                    del carry[col]
                else:
                    carry[col] = (text, remaining - 1)
                col += 1
                continue
            if current_cell is None:
                grid_row.append("")
                col += 1
                continue
            colspan, rowspan, text = current_cell["colspan"], current_cell["rowspan"], current_cell["text"]
            for span_offset in range(colspan):
                grid_row.append(text)
                if rowspan > 1:
                    carry[col + span_offset] = (text, rowspan - 1)
            col += colspan
            current_cell = next(cell_iter, None)
        grid.append(grid_row)
    width = max((len(grid_row) for grid_row in grid), default=0)
    for grid_row in grid:
        grid_row.extend("" for _ in range(width - len(grid_row)))
    return grid


def leading_header_row_count(rows: TableRows) -> int:
    """Number of leading rows containing a <th>; 0 when the table has none."""
    count = 0
    for row in rows:
        if not any(cell["tag"] == "th" for cell in row):
            break
        count += 1
    return count


def fallback_header_row_count(grid: list[list[str]]) -> int:
    """Header rows for a table without <th>: leading rows with an empty first column.

    A heuristic that holds for every observed component-versions table."""
    count = 0
    for row in grid:
        if row and row[0].strip():
            break
        count += 1
    return count


def effective_header_row_count(rows: TableRows, grid: list[list[str]]) -> int:
    """leading_header_row_count, else fallback_header_row_count; at least 1."""
    count = leading_header_row_count(rows)
    if count == 0:
        count = fallback_header_row_count(grid)
    return count or 1


def header_paths(grid: list[list[str]], header_row_count: int) -> list[list[str]]:
    """Per column, the distinct header texts above it, top first (e.g. ["Versie 4.8", "App"])."""
    width = len(grid[0]) if grid else 0
    paths: list[list[str]] = []
    for col in range(width):
        path: list[str] = []
        prev = None
        for row_idx in range(header_row_count):
            text = grid[row_idx][col] if col < len(grid[row_idx]) else ""
            if text and text != prev:
                path.append(text)
            prev = text
        paths.append(path)
    return paths


def _normalize(text: str) -> str:
    """Lowercase, collapse whitespace and drop hyphens (the page writes "Ontwikkel-partij")."""
    return " ".join(text.lower().replace("-", "").split())


def find_column(paths: list[list[str]], contains_all: list[str], candidates: list[int] | None = None) -> int | None:
    """First column in `candidates` whose joined header path contains all of `contains_all`, or None."""
    needles = [_normalize(needle) for needle in contains_all]
    indices = range(len(paths)) if candidates is None else candidates
    for idx in indices:
        joined = _normalize(" ".join(paths[idx]))
        if all(needle in joined for needle in needles):
            return idx
    return None


def find_versie_groups(paths: list[list[str]]) -> list[VersieGroup]:
    """(label, column indices) per top-level "Versie ..." header group, left to right.

    Labels change every release, so they are matched by prefix; groups[0] is the
    source version, groups[1] the target."""
    groups: list[VersieGroup] = []
    index_by_label: dict[str, int] = {}
    for idx, path in enumerate(paths):
        if not path or not _normalize(path[0]).startswith("versie"):
            continue
        label = path[0]
        if label not in index_by_label:
            index_by_label[label] = len(groups)
            groups.append((label, []))
        groups[index_by_label[label]][1].append(idx)
    return groups


# Only the App columns are required: "vendor" (product tables) and "used_by"
# (technical tables) each appear on only some tables, and the technical table
# has no separate Helm column.
REQUIRED_RELEASE_COLUMNS = ["source_app", "target_app"]


def select_release_columns(paths: list[list[str]]) -> ReleaseColumns:
    """Column index per ReleaseColumns field.

    "vendor" is the "Ontwikkelpartij" column, "first" is column 0. The app/helm
    columns stay None unless there are exactly two "Versie ..." groups. Helm
    columns are optional. A group with a single non-Helm column is its App column
    even without an "App" sub-header."""
    columns: ReleaseColumns = {
        "first": 0 if paths else None,
        "vendor": find_column(paths, ["ontwikkelpartij"]),
        "used_by": find_column(paths, ["used by"]),
        "source_app": None,
        "source_helm": None,
        "target_app": None,
        "target_helm": None,
    }
    match find_versie_groups(paths):
        case [(_, source_cols), (_, target_cols)]:
            source_app, source_helm = _app_and_helm_columns(paths, source_cols)
            target_app, target_helm = _app_and_helm_columns(paths, target_cols)
            columns.update(
                source_app=source_app, source_helm=source_helm, target_app=target_app, target_helm=target_helm
            )
        case _:
            pass
    return columns


def _app_and_helm_columns(paths: list[list[str]], group_cols: list[int]) -> tuple[int | None, int | None]:
    """(App, Helm) column of one "Versie ..." group."""
    helm_col = find_column(paths, ["helm"], candidates=group_cols)
    if len(group_cols) == 1 and helm_col is None:
        return group_cols[0], helm_col
    return find_column(paths, ["app"], candidates=group_cols), helm_col


def missing_required_release_columns(columns: ReleaseColumns):
    """REQUIRED_RELEASE_COLUMNS keys that resolved to None."""
    return [key for key in REQUIRED_RELEASE_COLUMNS if columns.get(key) is None]


# Looser than semver: MINOR/PATCH optional ("104", "3.20") and a "v" or "v."
# prefix allowed; still rejects run-together values ("5.4.3 5.4.4") and "?".
SEMVER_RE = re.compile(
    r"^(?:v\.?)?(?:0|[1-9]\d*)(?:\.(?:0|[1-9]\d*)){0,2}"
    r"(?:-(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*)?"
    r"(?:\+[0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*)?$"
)


def is_semver_compatible(version: str):
    """True if `version` matches SEMVER_RE, e.g. "1.27.4", "3.14-slim", "v.1.25.4", "104"; not "5.4.3 5.4.4" or "?"."""
    return bool(SEMVER_RE.match(version.strip()))


MAJOR_MINOR_RE = re.compile(r"(\d+)\.(\d+)")


def major_minor(text: str):
    """The first "MAJOR.MINOR" in `text` (e.g. "4.9" from "Versie 4.9" or "v4.9.2-rc1"), or None."""
    version_match = MAJOR_MINOR_RE.search(text)
    return f"{version_match.group(1)}.{version_match.group(2)}" if version_match else None
