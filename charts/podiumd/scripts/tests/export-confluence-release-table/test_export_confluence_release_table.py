"""resolve_token, extract_release_rows, check_target_matches_chart_version,
main — with fetch_page_html mocked out, so no network access or real
Confluence page is needed."""
import csv

import pytest


def write_chart_yaml(chart_dir, version):
    (chart_dir / "Chart.yaml").write_text(f"apiVersion: v2\nname: podiumd\nversion: {version}\n", encoding="utf-8")


@pytest.fixture(autouse=True)
def isolate_chart_dir(ecrt, tmp_path, monkeypatch):
    """extract_release_rows falls back to the real CHART_DIR (this
    script's actual parent directory) when no chart_dir is passed
    explicitly — tests that don't care about
    check_target_matches_chart_version must not depend on whatever
    charts/podiumd/Chart.yaml happens to say on disk (or which branch is
    checked out) at test-run time."""
    monkeypatch.setattr(ecrt, "CHART_DIR", tmp_path)

PRODUCT_TABLE_HTML = """
<h2>Product component versies</h2>
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

# "Technische component versies" tables don't have a development-partner
# column at all — "Used by" instead, which isn't required.
TECHNISCHE_TABLE_HTML = """
<h2>Technische component versies</h2>
<table>
<tbody>
<tr>
<th rowspan="2"></th>
<th rowspan="2">Used by</th>
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
<td>Elastic operator</td>
<td></td>
<td>3.4.0</td>
<td>3.4.0</td>
<td>3.5.0</td>
<td>3.5.0</td>
</tr>
</tbody>
</table>
"""

# A table with no heading at all above it — not under any of the target
# sections, so it's ignored outright, not merely "skipped for missing
# columns".
UNRELATED_TABLE_HTML = "<table><tr><th>Legend</th></tr><tr><td>n/a</td></tr></table>"

# Under a target heading, but genuinely missing the required App/Helm
# columns — this one SHOULD be reported as skipped.
INCOMPLETE_UNDER_TARGET_HEADING_HTML = (
    "<h2>Overige component versies</h2><table><tr><th>Naam</th></tr><tr><td>iets</td></tr></table>"
)


# --- normalize_version ---

def test_normalize_version_leaves_valid_semver_untouched(ecrt):
    assert ecrt.normalize_version("1.27.4") == "1.27.4"
    assert ecrt.normalize_version("9.10.1-slim") == "9.10.1-slim"


def test_normalize_version_leaves_allowed_variations_untouched(ecrt):
    """Missing patch component and a stray "." after a leading "v" are
    allowed variations, not something to flag — see
    lib.confluence_tables.SEMVER_RE."""
    assert ecrt.normalize_version("3.20") == "3.20"
    assert ecrt.normalize_version("3.14-slim") == "3.14-slim"
    assert ecrt.normalize_version("v.1.25.4") == "v.1.25.4"


def test_normalize_version_leaves_empty_value_untouched(ecrt):
    """No data at all for that cell isn't a malformed version — nothing
    to flag."""
    assert ecrt.normalize_version("") == ""


def test_normalize_version_replaces_non_semver_with_unknown(ecrt):
    assert ecrt.normalize_version("5.4.3 5.4.4") == "UNKNOWN"
    assert ecrt.normalize_version("?") == "UNKNOWN"


# --- resolve_token ---

def make_args(**overrides):
    from types import SimpleNamespace
    defaults = {"token_file": None, "token": None}
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_resolve_token_prefers_token_file(ecrt, tmp_path):
    token_file = tmp_path / "token.txt"
    token_file.write_text("  s3cr3t-from-file  \n", encoding="utf-8")
    args = make_args(token_file=str(token_file), token="ignored-since-file-wins")
    assert ecrt.resolve_token(args) == "s3cr3t-from-file"


def test_resolve_token_falls_back_to_token_arg(ecrt):
    args = make_args(token="s3cr3t-from-arg")
    assert ecrt.resolve_token(args) == "s3cr3t-from-arg"


def test_resolve_token_falls_back_to_env_var(ecrt, monkeypatch):
    monkeypatch.setenv("CONFLUENCE_API_TOKEN", "s3cr3t-from-env")
    args = make_args()
    assert ecrt.resolve_token(args) == "s3cr3t-from-env"


def test_resolve_token_prompts_as_last_resort(ecrt, monkeypatch):
    monkeypatch.delenv("CONFLUENCE_API_TOKEN", raising=False)
    monkeypatch.setattr(ecrt.getpass, "getpass", lambda prompt: "s3cr3t-from-prompt")
    args = make_args()
    assert ecrt.resolve_token(args) == "s3cr3t-from-prompt"


# Same shape as PRODUCT_TABLE_HTML, but the "App"/"Helm" sub-header row
# is plain <td>, not <th> — seen on the real podiumd page, where
# Confluence's own <th> tagging is inconsistent between a table's header
# rows.
PRODUCT_TABLE_INCONSISTENT_TH_HTML = PRODUCT_TABLE_HTML.replace(
    "<tr>\n<th>App</th>\n<th>Helm</th>\n<th>App</th>\n<th>Helm</th>\n</tr>",
    "<tr>\n<td>App</td>\n<td>Helm</td>\n<td>App</td>\n<td>Helm</td>\n</tr>",
)


# --- resolve_header_row_count ---

def test_resolve_header_row_count_extends_past_inconsistent_th_tagging(ecrt):
    from lib.confluence_tables import expand_grid, extract_tables
    _heading, rows = extract_tables(PRODUCT_TABLE_INCONSISTENT_TH_HTML)[0]
    grid = expand_grid(rows)
    assert ecrt.resolve_header_row_count(rows, grid) == 2


def test_extract_release_rows_handles_inconsistent_th_tagging(ecrt):
    """End-to-end: the same table with a <td>-tagged sub-header row must
    still resolve every required column, not just the ones a strict
    <th>-only header count would catch."""
    rows = ecrt.extract_release_rows(PRODUCT_TABLE_INCONSISTENT_TH_HTML)
    assert rows == [
        ["Product component versies", "ZAC", "Info(NL)", "5.0.0", "1.0.290", "5.1.0", "1.0.297"],
        ["Product component versies", "Open Zaak", "Maykin", "1.27.0", "1.14.0", "1.27.4", "1.14.2"],
    ]


# --- check_target_matches_chart_version ---

def test_check_target_matches_chart_version_silent_when_major_minor_matches(ecrt, tmp_path, capsys):
    write_chart_yaml(tmp_path, "4.9.0")
    ecrt.check_target_matches_chart_version(["Versie 4.9"], tmp_path)
    assert capsys.readouterr().err == ""


def test_check_target_matches_chart_version_warns_on_mismatch(ecrt, tmp_path, capsys):
    write_chart_yaml(tmp_path, "4.9.0")
    ecrt.check_target_matches_chart_version(["Versie 5.0"], tmp_path)
    err = capsys.readouterr().err
    assert "WARNING" in err
    assert "Chart.yaml version:        4.9.0" in err
    assert "'Versie 5.0'" in err


def test_check_target_matches_chart_version_ignores_patch(ecrt, tmp_path, capsys):
    """Chart.yaml at 4.9.3 (a patch release) must not warn just because
    the page still says "Versie 4.9" — only major.minor is compared."""
    write_chart_yaml(tmp_path, "4.9.3")
    ecrt.check_target_matches_chart_version(["Versie 4.9"], tmp_path)
    assert capsys.readouterr().err == ""


def test_check_target_matches_chart_version_dedupes_repeated_labels(ecrt, tmp_path, capsys):
    write_chart_yaml(tmp_path, "4.9.0")
    ecrt.check_target_matches_chart_version(["Versie 5.0", "Versie 5.0", "Versie 5.0"], tmp_path)
    err = capsys.readouterr().err
    assert err.count("'Versie 5.0'") == 1


def test_check_target_matches_chart_version_no_labels_is_silent(ecrt, tmp_path, capsys):
    write_chart_yaml(tmp_path, "4.9.0")
    ecrt.check_target_matches_chart_version([], tmp_path)
    assert capsys.readouterr().err == ""


def test_check_target_matches_chart_version_missing_chart_yaml_is_silent(ecrt, tmp_path, capsys):
    ecrt.check_target_matches_chart_version(["Versie 5.0"], tmp_path)
    assert capsys.readouterr().err == ""


# --- extract_release_rows ---

def test_extract_release_rows_matches_and_reports(ecrt, capsys):
    rows = ecrt.extract_release_rows(PRODUCT_TABLE_HTML)
    assert rows == [
        ["Product component versies", "ZAC", "Info(NL)", "5.0.0", "1.0.290", "5.1.0", "1.0.297"],
        ["Product component versies", "Open Zaak", "Maykin", "1.27.0", "1.14.0", "1.27.4", "1.14.2"],
    ]
    out = capsys.readouterr().out
    assert "2 row(s) matched" in out


def test_extract_release_rows_not_tied_to_specific_version_numbers(ecrt):
    """The page renames "Versie 4.8"/"Versie 4.9" every release — a table
    headed "Versie 5.0"/"Versie 5.1" instead must resolve exactly the
    same way, into "source"/"target" by column order, not by number."""
    html = PRODUCT_TABLE_HTML.replace("Versie 4.8", "Versie 5.0").replace("Versie 4.9", "Versie 5.1")
    rows = ecrt.extract_release_rows(html)
    assert rows == [
        ["Product component versies", "ZAC", "Info(NL)", "5.0.0", "1.0.290", "5.1.0", "1.0.297"],
        ["Product component versies", "Open Zaak", "Maykin", "1.27.0", "1.14.0", "1.27.4", "1.14.2"],
    ]


def test_extract_release_rows_replaces_non_semver_version_with_unknown_and_reports_count(ecrt, capsys):
    html = PRODUCT_TABLE_HTML.replace("<td>5.1.0</td>", "<td>?</td>")
    rows = ecrt.extract_release_rows(html)
    assert rows[0] == ["Product component versies", "ZAC", "Info(NL)", "5.0.0", "1.0.290", "UNKNOWN", "1.0.297"]
    out = capsys.readouterr().out
    assert "1 version value(s) were not semver-compatible — replaced with UNKNOWN" in out


def test_extract_release_rows_ignores_table_not_under_any_target_heading(ecrt, capsys):
    html = UNRELATED_TABLE_HTML + PRODUCT_TABLE_HTML
    rows = ecrt.extract_release_rows(html)
    assert len(rows) == 2
    out = capsys.readouterr().out
    assert "Found 2 table(s) on the page, 1 under a matching heading" in out
    assert "Legend" not in out  # the unrelated table was never even reported on


def test_extract_release_rows_reports_skip_for_incomplete_table_under_target_heading(ecrt, capsys):
    html = INCOMPLETE_UNDER_TARGET_HEADING_HTML + PRODUCT_TABLE_HTML
    rows = ecrt.extract_release_rows(html)
    assert len(rows) == 2
    out = capsys.readouterr().out
    assert '"Overige component versies": skipped (missing required column(s):' in out


def test_extract_release_rows_ontwikkelpartij_blank_when_table_has_none(ecrt):
    rows = ecrt.extract_release_rows(TECHNISCHE_TABLE_HTML)
    assert rows == [["Technische component versies", "Elastic operator", "", "3.4.0", "3.4.0", "3.5.0", "3.5.0"]]


def test_extract_release_rows_combines_multiple_sections(ecrt):
    rows = ecrt.extract_release_rows(PRODUCT_TABLE_HTML + TECHNISCHE_TABLE_HTML)
    assert [r[0] for r in rows] == ["Product component versies", "Product component versies",
                                     "Technische component versies"]


def test_extract_release_rows_custom_headings_overrides_default(ecrt):
    rows = ecrt.extract_release_rows(PRODUCT_TABLE_HTML + TECHNISCHE_TABLE_HTML,
                                      headings=["Technische component versies"])
    assert len(rows) == 1
    assert rows[0][0] == "Technische component versies"


def test_extract_release_rows_no_tables_raises(ecrt):
    with pytest.raises(SystemExit, match="no <table> found"):
        ecrt.extract_release_rows("<p>no tables here</p>")


def test_extract_release_rows_no_table_under_target_heading_raises(ecrt):
    with pytest.raises(SystemExit, match="no table found directly under any of"):
        ecrt.extract_release_rows(UNRELATED_TABLE_HTML)


def test_extract_release_rows_every_matching_table_incomplete_raises(ecrt):
    with pytest.raises(SystemExit, match="every matching-heading table was missing a required column"):
        ecrt.extract_release_rows(INCOMPLETE_UNDER_TARGET_HEADING_HTML)


def test_extract_release_rows_skips_fully_blank_rows(ecrt):
    html = PRODUCT_TABLE_HTML.replace(
        "<tr>\n<td>Open Zaak</td>",
        "<tr><td></td><td></td><td></td><td></td><td></td><td></td></tr>\n<tr>\n<td>Open Zaak</td>",
    )
    rows = ecrt.extract_release_rows(html)
    assert len(rows) == 2  # the all-blank row was skipped, not counted


def test_extract_release_rows_warns_when_target_does_not_match_chart_yaml(ecrt, tmp_path, capsys):
    """PRODUCT_TABLE_HTML's target heading is "Versie 4.9" — a
    Chart.yaml at a different minor version must trigger the warning."""
    write_chart_yaml(tmp_path, "5.0.0")
    ecrt.extract_release_rows(PRODUCT_TABLE_HTML, chart_dir=tmp_path)
    err = capsys.readouterr().err
    assert "WARNING" in err
    assert "'Versie 4.9'" in err


def test_extract_release_rows_silent_when_target_matches_chart_yaml(ecrt, tmp_path, capsys):
    write_chart_yaml(tmp_path, "4.9.0")
    ecrt.extract_release_rows(PRODUCT_TABLE_HTML, chart_dir=tmp_path)
    assert capsys.readouterr().err == ""


# --- main() integration ---

def test_main_writes_csv(ecrt, tmp_path, monkeypatch, capsys):
    output_path = tmp_path / "release-changes.csv"
    monkeypatch.setattr(ecrt.sys, "argv", [
        "export-confluence-release-table.py",
        "--url", "https://example.atlassian.net/wiki/spaces/PCP/pages/123/Title",
        "--user", "kees@info.nl",
        "--token", "s3cr3t",
        "--output", str(output_path),
    ])
    monkeypatch.setattr(ecrt, "fetch_page_html", lambda url, user, token: PRODUCT_TABLE_HTML)

    ecrt.main()

    with output_path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert rows[0] == ["sectie", "component", "ontwikkelpartij", "source version app", "source version helm",
                        "target version app", "target version helm"]
    assert rows[1] == ["Product component versies", "ZAC", "Info(NL)", "5.0.0", "1.0.290", "5.1.0", "1.0.297"]
    assert rows[2] == ["Product component versies", "Open Zaak", "Maykin", "1.27.0", "1.14.0", "1.27.4", "1.14.2"]
    out = capsys.readouterr().out
    assert f"Wrote 2 row(s) to {output_path}" in out


def test_main_passes_resolved_token_and_url_user_through(ecrt, tmp_path, monkeypatch):
    output_path = tmp_path / "out.csv"
    monkeypatch.setattr(ecrt.sys, "argv", [
        "export-confluence-release-table.py",
        "--url", "https://example.atlassian.net/wiki/spaces/PCP/pages/123/Title",
        "--user", "kees@info.nl",
        "--token", "s3cr3t",
        "--output", str(output_path),
    ])
    captured = {}

    def fake_fetch(url, user, token):
        captured.update(url=url, user=user, token=token)
        return PRODUCT_TABLE_HTML

    monkeypatch.setattr(ecrt, "fetch_page_html", fake_fetch)
    ecrt.main()
    assert captured == {
        "url": "https://example.atlassian.net/wiki/spaces/PCP/pages/123/Title",
        "user": "kees@info.nl",
        "token": "s3cr3t",
    }


def test_main_passes_custom_heading_flags_through(ecrt, tmp_path, monkeypatch):
    output_path = tmp_path / "out.csv"
    monkeypatch.setattr(ecrt.sys, "argv", [
        "export-confluence-release-table.py",
        "--url", "https://example.atlassian.net/wiki/spaces/PCP/pages/123/Title",
        "--user", "kees@info.nl",
        "--token", "s3cr3t",
        "--output", str(output_path),
        "--heading", "Technische component versies",
    ])
    monkeypatch.setattr(ecrt, "fetch_page_html",
                         lambda url, user, token: PRODUCT_TABLE_HTML + TECHNISCHE_TABLE_HTML)

    ecrt.main()

    with output_path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert len(rows) == 2  # header + the one Technische row only
    assert rows[1][0] == "Technische component versies"
