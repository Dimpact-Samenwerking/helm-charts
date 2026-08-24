"""Fetches a Confluence page's rendered HTML and extracts its <table>s into
plain-text grids (colspan/rowspan expanded), plus the specific "release
changes" column-matching used by export-confluence-release-table.py.
stdlib only (html.parser/urllib) — no bs4/requests dependency, matching
every other script in this toolset.

Auth is HTTP Basic with an Atlassian email + API token, same as Confluence
Cloud's REST API expects. Works against Confluence Cloud
("https://<site>.atlassian.net/wiki/...") and Server/DC ("https://<host>/
display/...") URLs alike — the API root differs (".../wiki/rest/api" vs
".../rest/api"), detected from the URL's own path."""
import base64
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

PAGE_ID_RE = re.compile(r"/pages/(\d+)")


def page_id_from_url(url):
    """The numeric content ID from a Confluence page URL — either the
    modern "/pages/<id>/<title-slug>" form or the older
    "?pageId=<id>" query-param form."""
    m = PAGE_ID_RE.search(url)
    if m:
        return m.group(1)
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    if "pageId" in query:
        return query["pageId"][0]
    raise SystemExit(f"error: could not find a page ID in {url}")


def api_base_url(url):
    """The REST API root for this Confluence site. Cloud sites serve the
    wiki under "/wiki" (API root ".../wiki/rest/api"); Server/DC sites
    serve it at the domain root (API root ".../rest/api")."""
    parsed = urllib.parse.urlparse(url)
    wiki_idx = parsed.path.find("/wiki/")
    api_path = f"{parsed.path[:wiki_idx]}/wiki/rest/api" if wiki_idx != -1 else "/rest/api"
    return f"{parsed.scheme}://{parsed.netloc}{api_path}"


def fetch_page_html(url, user, token, urlopen=urllib.request.urlopen):
    """The page's rendered body HTML (body.view.value) via the Confluence
    REST API. `urlopen` is overridable for tests."""
    page_id = page_id_from_url(url)
    api_url = f"{api_base_url(url)}/content/{page_id}?expand=body.view"
    auth = base64.b64encode(f"{user}:{token}".encode()).decode()
    request = urllib.request.Request(api_url, headers={
        "Authorization": f"Basic {auth}",
        "Accept": "application/json",
    })
    try:
        with urlopen(request) as response:
            data = json.load(response)
    except urllib.error.HTTPError as e:
        raise SystemExit(f"error: Confluence API request failed: HTTP {e.code} {e.reason}")
    except urllib.error.URLError as e:
        raise SystemExit(f"error: could not reach Confluence: {e.reason}")
    try:
        return data["body"]["view"]["value"]
    except KeyError:
        raise SystemExit("error: response had no body.view.value — check the URL and permissions")


class _TableExtractor(HTMLParser):
    """Builds one list of rows per top-level <table> in the document; each
    row is a list of {"tag", "colspan", "rowspan", "text"} cell dicts. A
    <table> nested inside a cell (Confluence layout tables, rare in a
    release-notes page) is ignored as structure and just falls into that
    cell's text — deliberately not supported, to keep this a plain-text
    extractor rather than a general HTML-to-DOM parser."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables = []
        self._table_stack = []
        self._row = None
        self._cell = None

    def handle_starttag(self, tag, attrs):
        if self._cell is not None:
            if tag == "br":
                self._cell["text"].append(" ")
            return
        attrs = dict(attrs)
        if tag == "table":
            self._table_stack.append([])
        elif tag == "tr" and self._table_stack:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = {
                "tag": tag,
                "colspan": _positive_int(attrs.get("colspan"), 1),
                "rowspan": _positive_int(attrs.get("rowspan"), 1),
                "text": [],
            }

    def handle_endtag(self, tag):
        if tag == "table" and self._table_stack:
            self.tables.append(self._table_stack.pop())
        elif tag == "tr" and self._row is not None and self._cell is None:
            if self._table_stack:
                self._table_stack[-1].append(self._row)
            self._row = None
        elif tag in ("td", "th") and self._cell is not None:
            text = " ".join("".join(self._cell["text"]).split())
            self._cell["text"] = text
            self._row.append(self._cell)
            self._cell = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell["text"].append(data)


def _positive_int(value, default):
    try:
        parsed = int(value)
        return parsed if parsed > 0 else default
    except (TypeError, ValueError):
        return default


def extract_tables(html_text):
    """One list-of-rows (unexpanded cell dicts, see _TableExtractor) per
    <table> found in `html_text`, in document order."""
    parser = _TableExtractor()
    parser.feed(html_text)
    return parser.tables


def expand_grid(rows):
    """A table's rows (unexpanded cell dicts) as a plain 2D grid of
    strings, with every colspan/rowspan expanded so each covered cell
    repeats the spanning cell's text and every row ends up the same
    width. A gap not covered by any cell (a malformed table) becomes an
    empty string rather than raising."""
    grid = []
    carry = {}  # column -> [text, remaining_rows_including_this_one]
    for row in rows:
        grid_row = []
        col = 0
        cell_iter = iter(row)
        current_cell = next(cell_iter, None)
        while current_cell is not None or any(k >= col for k in carry):
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
            for i in range(colspan):
                grid_row.append(text)
                if rowspan > 1:
                    carry[col + i] = (text, rowspan - 1)
            col += colspan
            current_cell = next(cell_iter, None)
        grid.append(grid_row)
    width = max((len(r) for r in grid), default=0)
    for r in grid:
        r.extend([""] * (width - len(r)))
    return grid


def leading_header_row_count(rows):
    """How many rows, starting from the top, contain at least one <th> —
    stops at the first row with none. 0 if the table uses no <th> at all
    (some Confluence tables render header cells as plain bold <td>s)."""
    count = 0
    for row in rows:
        if not any(cell["tag"] == "th" for cell in row):
            break
        count += 1
    return count


def header_paths(grid, header_row_count):
    """For every column, the stack of distinct header texts above it (top
    row first) — e.g. ["Versie 4.8", "App"] for a column under a
    colspan=2 "Versie 4.8" cell and its own "App" sub-header, or just
    ["Ontwikkelpartij"] for a column whose single header spans every
    header row via rowspan (deduped so it isn't repeated per row)."""
    width = len(grid[0]) if grid else 0
    paths = []
    for col in range(width):
        path = []
        prev = None
        for row_idx in range(header_row_count):
            text = grid[row_idx][col] if col < len(grid[row_idx]) else ""
            if text and text != prev:
                path.append(text)
            prev = text
        paths.append(path)
    return paths


def _normalize(text):
    return " ".join(text.lower().split())


def find_column(paths, contains_all):
    """Index of the first column whose header path contains every one of
    `contains_all` as a case-insensitive substring of the joined path
    text, or None if no column matches."""
    needles = [_normalize(n) for n in contains_all]
    for idx, path in enumerate(paths):
        joined = _normalize(" ".join(path))
        if all(needle in joined for needle in needles):
            return idx
    return None


# The exact column set export-confluence-release-table.py writes to CSV,
# in order: the table's own first column (whatever it's labeled — usually
# the component name), "Ontwikkelpartij", then App/Helm under each of
# "Versie 4.8" and "Versie 4.9". Matched by substring rather than exact
# text so a header phrased "versie 4.8" vs "Versie 4.8" vs "V4.8" all work.
RELEASE_COLUMN_SPECS = [
    ("ontwikkelpartij", ["ontwikkelpartij"]),
    ("v48_app", ["4.8", "app"]),
    ("v48_helm", ["4.8", "helm"]),
    ("v49_app", ["4.9", "app"]),
    ("v49_helm", ["4.9", "helm"]),
]


def select_release_columns(paths):
    """{"first": 0, "ontwikkelpartij": <idx>, "v48_app": <idx>, ...} — a
    value is None wherever no column matched that spec; "first" is always
    column 0 (the table's own leftmost column, whatever it's labeled),
    or None if the table has no columns at all."""
    columns = {"first": 0 if paths else None}
    for key, needles in RELEASE_COLUMN_SPECS:
        columns[key] = find_column(paths, needles)
    return columns
