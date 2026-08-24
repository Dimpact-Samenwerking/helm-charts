"""lib.confluence_tables — page_id_from_url, api_base_url, fetch_page_html,
extract_tables, expand_grid, leading_header_row_count, header_paths,
find_column, select_release_columns. fetch_page_html's `urlopen` is
injected directly, so no network access needed."""
import json
import urllib.error

import pytest

RELEASE_TABLE_HTML = """
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


def test_fetch_page_html_sends_basic_auth_and_returns_body_view(libconfluencetables):
    captured = {}

    def fake_urlopen(request):
        captured["url"] = request.full_url
        captured["auth"] = request.get_header("Authorization")
        return FakeResponse({"body": {"view": {"value": "<table></table>"}}})

    html = libconfluencetables.fetch_page_html(
        "https://example.atlassian.net/wiki/spaces/PCP/pages/123/Title",
        "kees@info.nl", "s3cr3t", urlopen=fake_urlopen,
    )
    assert html == "<table></table>"
    assert captured["url"] == "https://example.atlassian.net/wiki/rest/api/content/123?expand=body.view"
    import base64
    assert captured["auth"] == "Basic " + base64.b64encode(b"kees@info.nl:s3cr3t").decode()


def test_fetch_page_html_missing_body_view_raises(libconfluencetables):
    def fake_urlopen(request):
        return FakeResponse({"body": {}})

    with pytest.raises(SystemExit, match="no body.view.value"):
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
    rows = tables[0]
    assert len(rows) == 2
    assert [c["text"] for c in rows[0]] == ["A", "B"]
    assert [c["tag"] for c in rows[0]] == ["th", "th"]
    assert [c["text"] for c in rows[1]] == ["1", "2"]
    assert [c["tag"] for c in rows[1]] == ["td", "td"]


def test_extract_tables_multiple_tables_in_document_order(libconfluencetables):
    html = "<p>intro</p><table><tr><td>a</td></tr></table><table><tr><td>b</td></tr></table>"
    tables = libconfluencetables.extract_tables(html)
    assert len(tables) == 2
    assert tables[0][0][0]["text"] == "a"
    assert tables[1][0][0]["text"] == "b"


def test_extract_tables_collapses_whitespace_and_nested_tags(libconfluencetables):
    html = "<table><tr><td>  hello <strong>world</strong>  \n  again </td></tr></table>"
    tables = libconfluencetables.extract_tables(html)
    assert tables[0][0][0]["text"] == "hello world again"


def test_extract_tables_br_becomes_space(libconfluencetables):
    html = "<table><tr><td>line1<br/>line2</td></tr></table>"
    tables = libconfluencetables.extract_tables(html)
    assert tables[0][0][0]["text"] == "line1 line2"


def test_extract_tables_reads_colspan_rowspan_attrs(libconfluencetables):
    html = '<table><tr><th colspan="2" rowspan="3">X</th></tr></table>'
    tables = libconfluencetables.extract_tables(html)
    cell = tables[0][0][0]
    assert cell["colspan"] == 2
    assert cell["rowspan"] == 3


# --- expand_grid ---

def test_expand_grid_no_spans(libconfluencetables):
    tables = libconfluencetables.extract_tables(
        "<table><tr><td>a</td><td>b</td></tr><tr><td>c</td><td>d</td></tr></table>"
    )
    assert libconfluencetables.expand_grid(tables[0]) == [["a", "b"], ["c", "d"]]


def test_expand_grid_colspan_repeats_text_across_columns(libconfluencetables):
    tables = libconfluencetables.extract_tables(
        '<table><tr><th colspan="2">Versie 4.8</th></tr><tr><td>App</td><td>Helm</td></tr></table>'
    )
    grid = libconfluencetables.expand_grid(tables[0])
    assert grid[0] == ["Versie 4.8", "Versie 4.8"]
    assert grid[1] == ["App", "Helm"]


def test_expand_grid_rowspan_repeats_text_down_rows(libconfluencetables):
    tables = libconfluencetables.extract_tables(
        '<table><tr><th rowspan="2">Ontwikkelpartij</th><th>App</th></tr><tr><td>Helm</td></tr></table>'
    )
    grid = libconfluencetables.expand_grid(tables[0])
    assert grid[0] == ["Ontwikkelpartij", "App"]
    assert grid[1] == ["Ontwikkelpartij", "Helm"]


def test_expand_grid_pads_ragged_rows(libconfluencetables):
    tables = libconfluencetables.extract_tables("<table><tr><td>a</td><td>b</td></tr><tr><td>c</td></tr></table>")
    grid = libconfluencetables.expand_grid(tables[0])
    assert grid == [["a", "b"], ["c", ""]]


def test_expand_grid_full_release_table(libconfluencetables):
    tables = libconfluencetables.extract_tables(RELEASE_TABLE_HTML)
    grid = libconfluencetables.expand_grid(tables[0])
    assert grid[0] == ["", "Ontwikkelpartij", "Versie 4.8", "Versie 4.8", "Versie 4.9", "Versie 4.9"]
    assert grid[1] == ["", "Ontwikkelpartij", "App", "Helm", "App", "Helm"]
    assert grid[2] == ["ZAC", "Info(NL)", "5.0.0", "1.0.290", "5.1.0", "1.0.297"]


# --- leading_header_row_count ---

def test_leading_header_row_count_two_header_rows(libconfluencetables):
    tables = libconfluencetables.extract_tables(RELEASE_TABLE_HTML)
    assert libconfluencetables.leading_header_row_count(tables[0]) == 2


def test_leading_header_row_count_no_th_at_all(libconfluencetables):
    tables = libconfluencetables.extract_tables("<table><tr><td>A</td></tr><tr><td>1</td></tr></table>")
    assert libconfluencetables.leading_header_row_count(tables[0]) == 0


# --- header_paths ---

def test_header_paths_matches_release_table_structure(libconfluencetables):
    tables = libconfluencetables.extract_tables(RELEASE_TABLE_HTML)
    grid = libconfluencetables.expand_grid(tables[0])
    paths = libconfluencetables.header_paths(grid, header_row_count=2)
    assert paths[0] == []
    assert paths[1] == ["Ontwikkelpartij"]
    assert paths[2] == ["Versie 4.8", "App"]
    assert paths[3] == ["Versie 4.8", "Helm"]
    assert paths[4] == ["Versie 4.9", "App"]
    assert paths[5] == ["Versie 4.9", "Helm"]


# --- find_column / select_release_columns ---

def test_find_column_case_insensitive_substring_match(libconfluencetables):
    paths = [[], ["Ontwikkelpartij"], ["Versie 4.8", "App"]]
    assert libconfluencetables.find_column(paths, ["ontwikkelpartij"]) == 1
    assert libconfluencetables.find_column(paths, ["4.8", "app"]) == 2
    assert libconfluencetables.find_column(paths, ["4.9"]) is None


def test_select_release_columns_full_release_table(libconfluencetables):
    tables = libconfluencetables.extract_tables(RELEASE_TABLE_HTML)
    grid = libconfluencetables.expand_grid(tables[0])
    paths = libconfluencetables.header_paths(grid, header_row_count=2)
    columns = libconfluencetables.select_release_columns(paths)
    assert columns == {
        "first": 0, "ontwikkelpartij": 1, "v48_app": 2, "v48_helm": 3, "v49_app": 4, "v49_helm": 5,
    }


def test_select_release_columns_missing_column_is_none(libconfluencetables):
    paths = [[], ["Ontwikkelpartij"]]  # no Versie 4.8/4.9 columns at all
    columns = libconfluencetables.select_release_columns(paths)
    assert columns["ontwikkelpartij"] == 1
    assert columns["v48_app"] is None
    assert columns["v49_helm"] is None
