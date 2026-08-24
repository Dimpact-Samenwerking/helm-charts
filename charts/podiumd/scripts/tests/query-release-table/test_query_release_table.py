"""load_rows, matching_rows, display_value, print_table, main — with
DEFAULT_INPUT monkeypatched to a fixture CSV, so no dependency on a real
charts/podiumd/release-table.csv on disk."""
import pytest

CSV_TEXT = """\
section,vendor,used_by,component,source version app,source version helm,target version app,target version helm
Product,Info(NL),,ZAC,5.0.0,1.0.290,5.1.0,1.0.297
Product,Maykin,,Open Zaak,1.27.0,1.14.0,1.27.4,1.14.2
Technische,,,Elastic operator,3.4.0,3.4.0,,
Technische,,zac,Solr,8.11.0,8.11.0,8.11.0,8.11.0
Product,ZAC Team,,Some Component,1.0.0,1.0.0,1.0.0,1.0.0
"""


@pytest.fixture
def csv_path(tmp_path):
    path = tmp_path / "release-table.csv"
    path.write_text(CSV_TEXT, encoding="utf-8")
    return path


@pytest.fixture
def rows(qrt, csv_path):
    return qrt.load_rows(csv_path)


# --- load_rows ---

def test_load_rows_reads_all_data_rows(rows):
    assert len(rows) == 5
    assert rows[0]["component"] == "ZAC"


# --- matching_rows ---

def test_matching_rows_case_insensitive_substring(qrt, rows):
    matches = qrt.matching_rows(rows, "component", "zaak")
    assert [r["component"] for r in matches] == ["Open Zaak"]


def test_matching_rows_matches_multiple(qrt, rows):
    matches = qrt.matching_rows(rows, "section", "product")
    assert [r["component"] for r in matches] == ["ZAC", "Open Zaak", "Some Component"]


def test_matching_rows_no_match_is_empty(qrt, rows):
    assert qrt.matching_rows(rows, "vendor", "nonexistent") == []


def test_matching_rows_matches_vendor_column(qrt, rows):
    matches = qrt.matching_rows(rows, "vendor", "maykin")
    assert [r["component"] for r in matches] == ["Open Zaak"]


def test_matching_rows_matches_used_by_column(qrt, rows):
    matches = qrt.matching_rows(rows, "used_by", "zac")
    assert [r["component"] for r in matches] == ["Solr"]


# --- used_by_rows_for ---

def test_used_by_rows_for_finds_rows_by_component_substring(qrt, rows):
    """"zac" (Solr's used_by) is contained in "ZAC" (the matched row's own
    component name) — this is what lets a query on ANY column (not just
    "component") still pull in the tooling that component uses."""
    zac = [rows[0]]
    assert [r["component"] for r in qrt.used_by_rows_for(rows, zac)] == ["Solr"]


def test_used_by_rows_for_no_match_returns_empty(qrt, rows):
    open_zaak = [rows[1]]
    assert qrt.used_by_rows_for(rows, open_zaak) == []


def test_used_by_rows_for_excludes_the_matches_themselves(qrt, rows):
    """A matched row whose own used_by happens to substring-match its own
    component name (e.g. a "Kiss ..." component with used_by "kiss")
    must not be echoed back as its own "used by" result."""
    self_referential = {"component": "Kiss Thing", "used_by": "kiss",
                         "source version app": "1.0", "source version helm": "1.0",
                         "target version app": "1.0", "target version helm": "1.0"}
    all_rows = rows + [self_referential]
    assert qrt.used_by_rows_for(all_rows, [self_referential]) == []


# --- display_value ---

def test_display_value_target_empty_is_unchanged(qrt, rows):
    elastic = rows[2]
    assert qrt.display_value(elastic, "target version app") == "UNCHANGED"
    assert qrt.display_value(elastic, "target version helm") == "UNCHANGED"


def test_display_value_target_present_is_unaffected(qrt, rows):
    zac = rows[0]
    assert qrt.display_value(zac, "target version app") == "5.1.0"


def test_display_value_source_empty_stays_empty_not_unchanged(qrt, rows):
    """UNCHANGED is only ever a target-column concept — see the module
    docstring — an empty source value (not exercised by the fixture rows,
    but a legitimate "no data" case elsewhere in the pipeline) must not be
    relabeled."""
    elastic = dict(rows[2])
    elastic["source version app"] = ""
    assert qrt.display_value(elastic, "source version app") == ""


# --- print_table ---

def test_print_table_aligns_columns_with_header(qrt, capsys, rows):
    qrt.print_table([rows[0]])
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("component")
    assert "5.0.0" in out[1]
    assert "5.1.0" in out[1]


def test_print_table_shows_unchanged_for_empty_target(qrt, capsys, rows):
    qrt.print_table([rows[2]])
    out = capsys.readouterr().out
    assert "UNCHANGED" in out


# --- main ---

def run_main(qrt, monkeypatch, csv_path, argv):
    monkeypatch.setattr(qrt, "DEFAULT_INPUT", csv_path)
    monkeypatch.setattr("sys.argv", ["query-release-table.py"] + argv)


def test_main_prints_matches(qrt, monkeypatch, csv_path, capsys):
    run_main(qrt, monkeypatch, csv_path, ["component", "zac"])
    qrt.main()
    out = capsys.readouterr().out
    assert "ZAC" in out
    assert "5.1.0" in out


def test_main_prints_heading_above_primary_matches(qrt, monkeypatch, csv_path, capsys):
    """The primary matches need their own heading, distinct from "Used by
    ...:" below them — otherwise a single-row primary match (e.g. "Zaak -
    ZAC" itself, querying component "zac") reads as part of the used_by
    section instead of the actual match."""
    run_main(qrt, monkeypatch, csv_path, ["component", "zac"])
    qrt.main()
    out = capsys.readouterr().out
    assert "Matches for component 'zac':" in out
    lines = out.splitlines()
    heading_index = lines.index("Matches for component 'zac':")
    assert "ZAC" in lines[heading_index + 2]  # header row, then the ZAC data row


def test_main_component_query_also_shows_used_by_matches(qrt, monkeypatch, csv_path, capsys):
    run_main(qrt, monkeypatch, csv_path, ["component", "zac"])
    qrt.main()
    out = capsys.readouterr().out
    assert "Used by matched component(s):" in out
    assert "Solr" in out
    assert "8.11.0" in out


def test_main_component_query_omits_used_by_section_when_no_matches(qrt, monkeypatch, csv_path, capsys):
    run_main(qrt, monkeypatch, csv_path, ["component", "open zaak"])
    qrt.main()
    out = capsys.readouterr().out
    assert "Used by" not in out


def test_main_vendor_query_also_shows_used_by_matches(qrt, monkeypatch, csv_path, capsys):
    """Querying vendor "info" matches component "ZAC" — since "zac" (a
    Technische row's used_by) is contained in that component name, Solr
    must show up too, even though the query itself never touched
    "component" or the text "zac"."""
    run_main(qrt, monkeypatch, csv_path, ["vendor", "info"])
    qrt.main()
    out = capsys.readouterr().out
    assert "Used by matched component(s):" in out
    assert "Solr" in out


def test_main_vendor_query_omits_used_by_section_when_unrelated(qrt, monkeypatch, csv_path, capsys):
    """Vendor "Maykin" only matches "Open Zaak" — unrelated to any
    used_by value in the fixture, so no used_by section at all."""
    run_main(qrt, monkeypatch, csv_path, ["vendor", "maykin"])
    qrt.main()
    out = capsys.readouterr().out
    assert "Open Zaak" in out
    assert "Used by" not in out


def test_main_no_matches_exits_nonzero(qrt, monkeypatch, csv_path, capsys):
    run_main(qrt, monkeypatch, csv_path, ["component", "nonexistent"])
    with pytest.raises(SystemExit) as exc_info:
        qrt.main()
    assert exc_info.value.code != 0
    assert "no rows found" in capsys.readouterr().out


def test_main_invalid_column_prints_usage(qrt, monkeypatch, csv_path, capsys):
    run_main(qrt, monkeypatch, csv_path, ["bogus", "zac"])
    with pytest.raises(SystemExit) as exc_info:
        qrt.main()
    assert exc_info.value.code != 0
    assert "Usage:" in capsys.readouterr().out


def test_main_wrong_arg_count_prints_usage(qrt, monkeypatch, csv_path, capsys):
    run_main(qrt, monkeypatch, csv_path, ["component"])
    with pytest.raises(SystemExit) as exc_info:
        qrt.main()
    assert exc_info.value.code != 0
    assert "Usage:" in capsys.readouterr().out


def test_main_missing_input_file_errors(qrt, monkeypatch, tmp_path, capsys):
    missing = tmp_path / "does-not-exist.csv"
    monkeypatch.setattr(qrt, "DEFAULT_INPUT", missing)
    monkeypatch.setattr("sys.argv", ["query-release-table.py", "component", "zac"])
    with pytest.raises(SystemExit) as exc_info:
        qrt.main()
    assert exc_info.value.code != 0
    out = capsys.readouterr().out
    assert "not found" in out
    assert "export-confluence-release-table.py" in out
