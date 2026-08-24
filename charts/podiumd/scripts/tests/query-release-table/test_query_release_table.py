"""load_rows, matching_rows, display_value, print_table, main — with
DEFAULT_INPUT monkeypatched to a fixture CSV, so no dependency on a real
charts/podiumd/release-table.csv on disk."""
import pytest

CSV_TEXT = """\
section,vendor,component,source version app,source version helm,target version app,target version helm
Product,Info(NL),ZAC,5.0.0,1.0.290,5.1.0,1.0.297
Product,Maykin,Open Zaak,1.27.0,1.14.0,1.27.4,1.14.2
Technische,,Elastic operator,3.4.0,3.4.0,,
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
    assert len(rows) == 3
    assert rows[0]["component"] == "ZAC"


# --- matching_rows ---

def test_matching_rows_case_insensitive_substring(qrt, rows):
    matches = qrt.matching_rows(rows, "component", "zaak")
    assert [r["component"] for r in matches] == ["Open Zaak"]


def test_matching_rows_matches_multiple(qrt, rows):
    matches = qrt.matching_rows(rows, "section", "product")
    assert [r["component"] for r in matches] == ["ZAC", "Open Zaak"]


def test_matching_rows_no_match_is_empty(qrt, rows):
    assert qrt.matching_rows(rows, "vendor", "nonexistent") == []


def test_matching_rows_matches_vendor_column(qrt, rows):
    matches = qrt.matching_rows(rows, "vendor", "maykin")
    assert [r["component"] for r in matches] == ["Open Zaak"]


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
