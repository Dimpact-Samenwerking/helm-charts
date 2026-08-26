"""lib.confluence_tables — page_id_from_url, api_base_url, fetch_page_html,
extract_tables, tables_under_headings, expand_grid,
leading_header_row_count, fallback_header_row_count,
effective_header_row_count, header_paths, find_column,
find_versie_groups, select_release_columns,
missing_required_release_columns, is_semver_compatible, major_minor.
fetch_page_html's `urlopen` is injected directly, so no network access
needed."""
import json
import urllib.error

import pytest

RELEASE_TABLE_HTML = """
<h2>Technische component versies</h2>
<table>
<tbody>
<tr>
<th rowspan="2"></th>
<th rowspan="2">Ontwikkelpartij</th>
<th colspan="2">Versie 4.8</th>
<th colspan="2">Versie 4.9</th>
</tr>
<tr>
<th>App</th>
<th>Helm</th>
<th>App</th>
<th>Helm</th>
</tr>
<tr>
<td>ZAC</td>
<td>Info(NL)</td>
<td>5.0.0</td>
<td>1.0.290</td>
<td>5.1.0</td>
<td>1.0.297</td>
</tr>
<tr>
<td>Open Zaak</td>
<td>Maykin</td>
<td>1.27.0</td>
<td>1.14.0</td>
<td>1.27.4</td>
<td>1.14.2</td>
</tr>
</tbody>
</table>
"""

# Same table, but header cells are plain <td> (no <th> at all) — how
# Confluence storage format sometimes renders it.
NO_TH_RELEASE_TABLE_HTML = RELEASE_TABLE_HTML.replace("<th", "<td").replace("</th>", "</td>")


# --- page_id_from_url ---

def test_page_id_from_url_modern_pages_path(libconfluencetables):
    url = "https://example.atlassian.net/wiki/spaces/PCP/pages/123456789/PodiumD+4.9.0"
    assert libconfluencetables.page_id_from_url(url) == "123456789"


def test_page_id_from_url_legacy_query_param(libconfluencetables):
    url = "https://confluence.example.com/pages/viewpage.action?pageId=987654"
    assert libconfluencetables.page_id_from_url(url) == "987654"


def test_page_id_from_url_no_match_raises(libconfluencetables):
    with pytest.raises(SystemExit, match="could not find a page ID"):
        libconfluencetables.page_id_from_url("https://example.atlassian.net/wiki/spaces/PCP/overview")


# --- api_base_url ---

def test_api_base_url_cloud_site(libconfluencetables):
    url = "https://example.atlassian.net/wiki/spaces/PCP/pages/123/Title"
    assert libconfluencetables.api_base_url(url) == "https://example.atlassian.net/wiki/rest/api"


def test_api_base_url_server_site(libconfluencetables):
    url = "https://confluence.example.com/display/PCP/Title"
    assert libconfluencetables.api_base_url(url) == "https://confluence.example.com/rest/api"


# --- fetch_page_html ---

class FakeResponse:
    def __init__(self, payload):
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_fetch_page_html_sends_basic_auth_and_returns_body_storage(libconfluencetables):
    captured = {}

    def fake_urlopen(request):
        captured["url"] = request.full_url
        captured["auth"] = request.get_header("Authorization")
        return FakeResponse({"body": {"storage": {"value": "<table></table>"}}})

    html = libconfluencetables.fetch_page_html(
        "https://example.atlassian.net/wiki/spaces/PCP/pages/123/Title",
        "kees@info.nl", "s3cr3t", urlopen=fake_urlopen,
    )
    assert html == "<table></table>"
    assert captured["url"] == "https://example.atlassian.net/wiki/rest/api/content/123?expand=body.storage"
    import base64
    assert captured["auth"] == "Basic " + base64.b64encode(b"kees@info.nl:s3cr3t").decode()


def test_fetch_page_html_missing_body_storage_raises(libconfluencetables):
    def fake_urlopen(request):
        return FakeResponse({"body": {}})

    with pytest.raises(SystemExit, match="no body.storage.value"):
        libconfluencetables.fetch_page_html(
            "https://example.atlassian.net/wiki/spaces/PCP/pages/123/Title",
            "kees@info.nl", "s3cr3t", urlopen=fake_urlopen,
        )


def test_fetch_page_html_http_error_raises(libconfluencetables):
    def fake_urlopen(request):
        raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {}, None)

    with pytest.raises(SystemExit, match="HTTP 401"):
        libconfluencetables.fetch_page_html(
            "https://example.atlassian.net/wiki/spaces/PCP/pages/123/Title",
            "kees@info.nl", "wrong-token", urlopen=fake_urlopen,
        )


def test_fetch_page_html_url_error_raises(libconfluencetables):
    def fake_urlopen(request):
        raise urllib.error.URLError("name resolution failed")

    with pytest.raises(SystemExit, match="could not reach Confluence"):
        libconfluencetables.fetch_page_html(
            "https://example.atlassian.net/wiki/spaces/PCP/pages/123/Title",
            "kees@info.nl", "s3cr3t", urlopen=fake_urlopen,
        )


# --- extract_tables ---

def test_extract_tables_simple(libconfluencetables):
    html = "<table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table>"
    tables = libconfluencetables.extract_tables(html)
    assert len(tables) == 1
    heading, rows = tables[0]
    assert heading is None
    assert len(rows) == 2
    assert [c["text"] for c in rows[0]] == ["A", "B"]
    assert [c["tag"] for c in rows[0]] == ["th", "th"]
    assert [c["text"] for c in rows[1]] == ["1", "2"]
    assert [c["tag"] for c in rows[1]] == ["td", "td"]


def test_extract_tables_multiple_tables_in_document_order(libconfluencetables):
    html = "<p>intro</p><table><tr><td>a</td></tr></table><table><tr><td>b</td></tr></table>"
    tables = libconfluencetables.extract_tables(html)
    assert len(tables) == 2
    assert tables[0][1][0][0]["text"] == "a"
    assert tables[1][1][0][0]["text"] == "b"


def test_extract_tables_collapses_whitespace_and_nested_tags(libconfluencetables):
    html = "<table><tr><td>  hello <strong>world</strong>  \n  again </td></tr></table>"
    tables = libconfluencetables.extract_tables(html)
    assert tables[0][1][0][0]["text"] == "hello world again"


def test_extract_tables_br_becomes_space(libconfluencetables):
    html = "<table><tr><td>line1<br/>line2</td></tr></table>"
    tables = libconfluencetables.extract_tables(html)
    assert tables[0][1][0][0]["text"] == "line1 line2"


def test_extract_tables_adjacent_paragraphs_separated_by_hr_do_not_run_together(libconfluencetables):
    """Real podiumd page content: a version-history cell rendered as
    "<p>5.4.3</p><hr/><p>5.4.4</p>" — without this, the two values
    concatenate into "5.4.35.4.4" instead of staying distinguishable."""
    html = "<table><tr><td><p>5.4.3</p><hr/><p>5.4.4</p></td></tr></table>"
    tables = libconfluencetables.extract_tables(html)
    assert tables[0][1][0][0]["text"] == "5.4.3 5.4.4"


def test_extract_tables_single_paragraph_cell_has_no_stray_whitespace(libconfluencetables):
    html = "<table><tr><td><p>ZAC</p></td></tr></table>"
    tables = libconfluencetables.extract_tables(html)
    assert tables[0][1][0][0]["text"] == "ZAC"


def test_extract_tables_nested_table_does_not_leak_extra_columns(libconfluencetables):
    """A table nested inside a cell (seen on the real podiumd release page:
    a CVE-details table embedded in a "what changed" cell) must not be
    mistaken for a second top-level table, and its own tr/td/th closing
    tags must not prematurely close the OUTER cell — either bug would leak
    the nested table's cells out as bogus extra columns of the outer
    table."""
    html = (
        "<table><tr><td>a</td><td>before "
        "<table><tr><td>nested1</td><td>nested2</td></tr></table>"
        " after</td></tr></table>"
    )
    tables = libconfluencetables.extract_tables(html)
    assert len(tables) == 1  # the nested <table> must not register as its own table
    _heading, rows = tables[0]
    assert len(rows) == 1
    assert len(rows[0]) == 2  # not leaked into 3+ cells
    assert rows[0][0]["text"] == "a"
    assert rows[0][1]["text"] == "before nested1nested2 after"


def test_extract_tables_reads_colspan_rowspan_attrs(libconfluencetables):
    html = '<table><tr><th colspan="2" rowspan="3">X</th></tr></table>'
    tables = libconfluencetables.extract_tables(html)
    cell = tables[0][1][0][0]
    assert cell["colspan"] == 2
    assert cell["rowspan"] == 3


def test_extract_tables_associates_nearest_preceding_heading(libconfluencetables):
    html = (
        "<h2>Intro</h2><p>no table here</p>"
        "<h2>Section A</h2><table><tr><td>a1</td></tr></table><table><tr><td>a2</td></tr></table>"
        "<h3>Section B</h3><table><tr><td>b1</td></tr></table>"
    )
    tables = libconfluencetables.extract_tables(html)
    headings = [h for h, _rows in tables]
    assert headings == ["Section A", "Section A", "Section B"]


def test_extract_tables_heading_none_before_any_heading(libconfluencetables):
    html = "<table><tr><td>a</td></tr></table><h2>Later</h2><table><tr><td>b</td></tr></table>"
    tables = libconfluencetables.extract_tables(html)
    assert tables[0][0] is None
    assert tables[1][0] == "Later"


def test_extract_tables_heading_nested_inline_tags_collapsed(libconfluencetables):
    html = "<h2>  Product   <strong>component</strong> versies  </h2><table><tr><td>x</td></tr></table>"
    tables = libconfluencetables.extract_tables(html)
    assert tables[0][0] == "Product component versies"


# --- tables_under_headings ---

def test_tables_under_headings_case_insensitive_exact_match(libconfluencetables):
    tables = [("Product component versies", "rowsA"), ("Overige component versies", "rowsB"),
              (None, "rowsC"), ("Unrelated", "rowsD")]
    matched = libconfluencetables.tables_under_headings(tables, ["product component versies"])
    assert matched == [("Product component versies", "rowsA")]


def test_tables_under_headings_multiple_wanted_headings_preserve_order(libconfluencetables):
    tables = [("A", "rows1"), ("B", "rows2"), ("A", "rows3")]
    matched = libconfluencetables.tables_under_headings(tables, ["a", "b"])
    assert matched == [("A", "rows1"), ("B", "rows2"), ("A", "rows3")]


def test_tables_under_headings_no_match_returns_empty(libconfluencetables):
    assert libconfluencetables.tables_under_headings([("Other", "rows")], ["Wanted"]) == []


# --- expand_grid ---

def test_expand_grid_no_spans(libconfluencetables):
    tables = libconfluencetables.extract_tables(
        "<table><tr><td>a</td><td>b</td></tr><tr><td>c</td><td>d</td></tr></table>"
    )
    assert libconfluencetables.expand_grid(tables[0][1]) == [["a", "b"], ["c", "d"]]


def test_expand_grid_colspan_repeats_text_across_columns(libconfluencetables):
    tables = libconfluencetables.extract_tables(
        '<table><tr><th colspan="2">Versie 4.8</th></tr><tr><td>App</td><td>Helm</td></tr></table>'
    )
    grid = libconfluencetables.expand_grid(tables[0][1])
    assert grid[0] == ["Versie 4.8", "Versie 4.8"]
    assert grid[1] == ["App", "Helm"]


def test_expand_grid_rowspan_repeats_text_down_rows(libconfluencetables):
    tables = libconfluencetables.extract_tables(
        '<table><tr><th rowspan="2">Ontwikkelpartij</th><th>App</th></tr><tr><td>Helm</td></tr></table>'
    )
    grid = libconfluencetables.expand_grid(tables[0][1])
    assert grid[0] == ["Ontwikkelpartij", "App"]
    assert grid[1] == ["Ontwikkelpartij", "Helm"]


def test_expand_grid_pads_ragged_rows(libconfluencetables):
    tables = libconfluencetables.extract_tables("<table><tr><td>a</td><td>b</td></tr><tr><td>c</td></tr></table>")
    grid = libconfluencetables.expand_grid(tables[0][1])
    assert grid == [["a", "b"], ["c", ""]]


def test_expand_grid_full_release_table(libconfluencetables):
    tables = libconfluencetables.extract_tables(RELEASE_TABLE_HTML)
    grid = libconfluencetables.expand_grid(tables[0][1])
    assert grid[0] == ["", "Ontwikkelpartij", "Versie 4.8", "Versie 4.8", "Versie 4.9", "Versie 4.9"]
    assert grid[1] == ["", "Ontwikkelpartij", "App", "Helm", "App", "Helm"]
    assert grid[2] == ["ZAC", "Info(NL)", "5.0.0", "1.0.290", "5.1.0", "1.0.297"]


# --- leading_header_row_count / fallback_header_row_count / effective_header_row_count ---

def test_leading_header_row_count_two_header_rows(libconfluencetables):
    tables = libconfluencetables.extract_tables(RELEASE_TABLE_HTML)
    assert libconfluencetables.leading_header_row_count(tables[0][1]) == 2


def test_leading_header_row_count_no_th_at_all(libconfluencetables):
    tables = libconfluencetables.extract_tables("<table><tr><td>A</td></tr><tr><td>1</td></tr></table>")
    assert libconfluencetables.leading_header_row_count(tables[0][1]) == 0


def test_fallback_header_row_count_blank_first_column_leading_rows(libconfluencetables):
    grid = [["", "Versie 4.8", "Versie 4.8"], ["", "App", "Helm"], ["ZAC", "5.0.0", "1.0.290"]]
    assert libconfluencetables.fallback_header_row_count(grid) == 2


def test_fallback_header_row_count_no_blank_leading_rows(libconfluencetables):
    grid = [["ZAC", "5.0.0"]]
    assert libconfluencetables.fallback_header_row_count(grid) == 0


def test_effective_header_row_count_prefers_th_based_count(libconfluencetables):
    tables = libconfluencetables.extract_tables(RELEASE_TABLE_HTML)
    rows = tables[0][1]
    grid = libconfluencetables.expand_grid(rows)
    assert libconfluencetables.effective_header_row_count(rows, grid) == 2


def test_effective_header_row_count_falls_back_when_no_th(libconfluencetables):
    """The same release table, but with every header cell rendered as
    plain <td> instead of <th> — some Confluence storage-format tables
    do this."""
    tables = libconfluencetables.extract_tables(NO_TH_RELEASE_TABLE_HTML)
    rows = tables[0][1]
    grid = libconfluencetables.expand_grid(rows)
    assert libconfluencetables.leading_header_row_count(rows) == 0  # no <th> at all
    assert libconfluencetables.effective_header_row_count(rows, grid) == 2  # fallback still finds it


def test_effective_header_row_count_never_zero(libconfluencetables):
    tables = libconfluencetables.extract_tables("<table><tr><td>a</td><td>b</td></tr></table>")
    rows = tables[0][1]
    grid = libconfluencetables.expand_grid(rows)
    assert libconfluencetables.effective_header_row_count(rows, grid) == 1


# --- header_paths ---

def test_header_paths_matches_release_table_structure(libconfluencetables):
    tables = libconfluencetables.extract_tables(RELEASE_TABLE_HTML)
    grid = libconfluencetables.expand_grid(tables[0][1])
    paths = libconfluencetables.header_paths(grid, header_row_count=2)
    assert paths[0] == []
    assert paths[1] == ["Ontwikkelpartij"]
    assert paths[2] == ["Versie 4.8", "App"]
    assert paths[3] == ["Versie 4.8", "Helm"]
    assert paths[4] == ["Versie 4.9", "App"]
    assert paths[5] == ["Versie 4.9", "Helm"]


# --- find_column ---

def test_find_column_case_insensitive_substring_match(libconfluencetables):
    paths = [[], ["Ontwikkelpartij"], ["Versie 4.8", "App"]]
    assert libconfluencetables.find_column(paths, ["ontwikkelpartij"]) == 1
    assert libconfluencetables.find_column(paths, ["4.8", "app"]) == 2
    assert libconfluencetables.find_column(paths, ["4.9"]) is None


def test_find_column_tolerates_hyphenated_header(libconfluencetables):
    """The real podiumd page spells it "Ontwikkel-partij" — a hyphen must
    not break the match against the "ontwikkelpartij" needle."""
    paths = [[], ["Ontwikkel-partij"]]
    assert libconfluencetables.find_column(paths, ["ontwikkelpartij"]) == 1


def test_find_column_restricts_to_candidates(libconfluencetables):
    paths = [["Versie 4.8", "App"], ["Versie 4.9", "App"]]
    assert libconfluencetables.find_column(paths, ["app"], candidates=[1]) == 1
    assert libconfluencetables.find_column(paths, ["app"], candidates=[0]) == 0


# --- find_versie_groups ---

def test_find_versie_groups_orders_by_first_appearance(libconfluencetables):
    paths = [[], ["Ontwikkelpartij"], ["Versie 4.8", "App"], ["Versie 4.8", "Helm"],
             ["Versie 4.9", "App"], ["Versie 4.9", "Helm"]]
    groups = libconfluencetables.find_versie_groups(paths)
    assert groups == [("Versie 4.8", [2, 3]), ("Versie 4.9", [4, 5])]


def test_find_versie_groups_not_tied_to_specific_version_numbers(libconfluencetables):
    """The page renames these headers every release — matching only
    checks the label starts with "Versie", never a specific number."""
    paths = [["Versie 5.0", "App"], ["Versie 5.1", "Helm"]]
    groups = libconfluencetables.find_versie_groups(paths)
    assert [label for label, _cols in groups] == ["Versie 5.0", "Versie 5.1"]


def test_find_versie_groups_case_insensitive(libconfluencetables):
    paths = [["versie 4.8", "App"]]
    groups = libconfluencetables.find_versie_groups(paths)
    assert groups == [("versie 4.8", [0])]


def test_find_versie_groups_ignores_non_versie_columns(libconfluencetables):
    paths = [[], ["Ontwikkelpartij"], ["Wijziging"]]
    assert libconfluencetables.find_versie_groups(paths) == []


# --- select_release_columns / missing_required_release_columns ---

def test_select_release_columns_full_release_table(libconfluencetables):
    tables = libconfluencetables.extract_tables(RELEASE_TABLE_HTML)
    grid = libconfluencetables.expand_grid(tables[0][1])
    paths = libconfluencetables.header_paths(grid, header_row_count=2)
    columns = libconfluencetables.select_release_columns(paths)
    assert columns == {
        "first": 0, "vendor": 1, "used_by": None,
        "source_app": 2, "source_helm": 3, "target_app": 4, "target_helm": 5,
    }


def test_select_release_columns_not_tied_to_specific_version_numbers(libconfluencetables):
    paths = [[], ["Ontwikkelpartij"], ["Versie 5.0", "App"], ["Versie 5.0", "Helm"],
             ["Versie 5.1", "App"], ["Versie 5.1", "Helm"]]
    columns = libconfluencetables.select_release_columns(paths)
    assert columns == {
        "first": 0, "vendor": 1, "used_by": None,
        "source_app": 2, "source_helm": 3, "target_app": 4, "target_helm": 5,
    }


def test_select_release_columns_missing_column_is_none(libconfluencetables):
    paths = [[], ["Ontwikkelpartij"]]  # no Versie ... columns at all
    columns = libconfluencetables.select_release_columns(paths)
    assert columns["vendor"] == 1
    assert columns["used_by"] is None
    assert columns["source_app"] is None
    assert columns["target_helm"] is None


def test_select_release_columns_finds_used_by(libconfluencetables):
    """A "Technische component versies"-style table has "Used by" instead
    of "Ontwikkelpartij" — naming which product/Common Ground component
    pulls that piece of tooling in."""
    paths = [[], ["Used by"], ["Versie 4.8", "App"], ["Versie 4.8", "Helm"],
             ["Versie 4.9", "App"], ["Versie 4.9", "Helm"]]
    columns = libconfluencetables.select_release_columns(paths)
    assert columns["vendor"] is None
    assert columns["used_by"] == 1


def test_select_release_columns_none_when_not_exactly_two_versie_groups(libconfluencetables):
    """One "Versie ..." group (or three+) isn't the source/target pair
    this export expects — leave everything unresolved rather than
    guessing which one(s) to use."""
    paths = [[], ["Versie 4.9", "App"], ["Versie 4.9", "Helm"]]
    columns = libconfluencetables.select_release_columns(paths)
    assert columns["source_app"] is None
    assert columns["target_app"] is None


def test_missing_required_release_columns_vendor_not_required(libconfluencetables):
    """A "Used by"-style table with no Ontwikkelpartij column at all, but
    every App/Helm column present, must report nothing missing."""
    paths = [[], ["Used by"], ["Versie 4.8", "App"], ["Versie 4.8", "Helm"],
             ["Versie 4.9", "App"], ["Versie 4.9", "Helm"]]
    columns = libconfluencetables.select_release_columns(paths)
    assert columns["vendor"] is None
    assert libconfluencetables.missing_required_release_columns(columns) == []


def test_missing_required_release_columns_reports_missing_app_helm(libconfluencetables):
    paths = [[], ["Ontwikkelpartij"], ["Versie 4.8", "App"], ["Versie 4.9", "App"]]  # no Helm columns at all
    columns = libconfluencetables.select_release_columns(paths)
    missing = libconfluencetables.missing_required_release_columns(columns)
    assert set(missing) == {"source_helm", "target_helm"}


# --- is_semver_compatible ---

@pytest.mark.parametrize("version", [
    "1.27.4",
    "v1.25.4",
    "9.10.1-slim",
    "1.38.0-glibc",
    "3.14.7-slim",
    "0.9.1",
    "1.0.0+build.1",
    "3.20",               # allowed variation: missing patch component
    "3.14-slim",          # same, with a suffix
    "v.1.25.4",           # allowed variation: stray dot after the "v"
])
def test_is_semver_compatible_accepts_valid_versions(libconfluencetables, version):
    assert libconfluencetables.is_semver_compatible(version) is True


@pytest.mark.parametrize("version", [
    "5.4.3 5.4.4",        # two values run together
    "0.9.0 0.9.1 (per 4.8.5)",
    "?",
    "",
])
def test_is_semver_compatible_rejects_invalid_versions(libconfluencetables, version):
    assert libconfluencetables.is_semver_compatible(version) is False


# --- major_minor ---

def test_major_minor_strips_patch_component(libconfluencetables):
    assert libconfluencetables.major_minor("4.9.0") == "4.9"


def test_major_minor_finds_pattern_inside_a_label(libconfluencetables):
    assert libconfluencetables.major_minor("Versie 4.9") == "4.9"
    assert libconfluencetables.major_minor("v4.9.2-rc1") == "4.9"


def test_major_minor_no_pattern_returns_none(libconfluencetables):
    assert libconfluencetables.major_minor("unknown") is None
    assert libconfluencetables.major_minor("") is None
