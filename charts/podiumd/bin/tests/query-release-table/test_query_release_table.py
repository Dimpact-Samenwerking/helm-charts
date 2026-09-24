"""matching_rows, component_matches, used_by_rows_for,
display_value, print_table, main — with DEFAULT_INPUT monkeypatched to a
fixture CSV, so no dependency on a real charts/podiumd/etc/release-table.csv
on disk."""

from pathlib import Path
from types import ModuleType

import pytest

from lib.release_table.csv_rows import read_release_table

CSV_TEXT = """\
section,vendor,used_by,name,component,alias,image_basename,source_version_app,source_version_helm,target_version_app,target_version_helm
Product,Info(NL),,ZAC,zaakafhandelcomponent,zac,zaakafhandelcomponent,5.0.0,1.0.290,5.1.0,1.0.297
Product,Maykin,,Open Zaak,openzaak,,,1.27.0,1.14.0,1.27.4,1.14.2
Technische,,,Elastic operator,,,,3.4.0,3.4.0,,
Technische,,zac,Solr,,,solr,8.11.0,8.11.0,8.11.0,8.11.0
Product,ZAC Team,,Some Component,,,,1.0.0,1.0.0,1.0.0,1.0.0
Product,ICATT,,Interne Taak Afhandeling,internetaakafhandeling,ita,,3.2.0,3.2.0,3.3.0,3.3.0
Technische,,ita,ITA Poller,,,,1.0.0,1.0.0,1.0.0,1.0.0
Product,ICATT,,Contact (KISS),kiss-chart,kiss,kiss-frontend,2.2.3,2.2.3,3.0.0,3.0.0
Technische,,kiss,Kiss Elastic Sync,,,kiss-elastic-sync,0.3.3,0.3.3,3.0.0,3.0.0
Technische,,kiss,PodiumD Adapter,,,podiumd-adapter,0.6.6,0.6.6,0.6.7,0.6.7
"""


@pytest.fixture
def csv_path(tmp_path: Path):
    path = tmp_path / "release-table.csv"
    path.write_text(CSV_TEXT, encoding="utf-8")
    return path


@pytest.fixture
def rows(qrt: ModuleType, csv_path):
    return read_release_table(csv_path)


# --- read_release_table ---


def test_read_release_table_reads_all_data_rows(rows):
    assert len(rows) == 10
    assert rows[0]["name"] == "ZAC"


# --- matching_rows ---


def test_matching_rows_case_insensitive_substring(qrt: ModuleType, rows):
    matches = qrt.matching_rows(rows, "name", "zaak")
    assert [r["name"] for r in matches] == ["Open Zaak"]


def test_matching_rows_matches_multiple(qrt: ModuleType, rows):
    matches = qrt.matching_rows(rows, "section", "product")
    assert [r["name"] for r in matches] == [
        "ZAC",
        "Open Zaak",
        "Some Component",
        "Interne Taak Afhandeling",
        "Contact (KISS)",
    ]


def test_matching_rows_no_match_is_empty(qrt: ModuleType, rows):
    assert qrt.matching_rows(rows, "vendor", "nonexistent") == []


def test_matching_rows_matches_vendor_column(qrt: ModuleType, rows):
    matches = qrt.matching_rows(rows, "vendor", "maykin")
    assert [r["name"] for r in matches] == ["Open Zaak"]


def test_matching_rows_matches_used_by_column(qrt: ModuleType, rows):
    matches = qrt.matching_rows(rows, "used_by", "zac")
    assert [r["name"] for r in matches] == ["Solr"]


# --- used_by_rows_for ---


def test_used_by_rows_for_finds_rows_by_name_substring(qrt: ModuleType, rows):
    """ "zac" (Solr's used_by) is contained in "ZAC" (the matched row's own
    name) — this is what lets a query on ANY column still pull in the
    tooling that row uses."""
    zac = [rows[0]]
    assert [r["name"] for r in qrt.used_by_rows_for(rows, zac)] == ["Solr"]


def test_used_by_rows_for_matches_whole_words_only(qrt: ModuleType) -> None:
    """used_by relates to a name at whole words (word_contains): "mi"
    never pulls in a row for "Admin User", "keycloak-operator" does
    match "Keycloak Operator"."""
    admin = {"name": "Admin User", "used_by": "", "alias": ""}
    operator = {"name": "Keycloak Operator", "used_by": "", "alias": ""}
    mi = {"name": "MI image", "used_by": "mi", "alias": ""}
    postgres = {"name": "Postgres", "used_by": "keycloak-operator", "alias": ""}
    rows = [admin, operator, mi, postgres]
    assert qrt.used_by_rows_for(rows, [admin]) == []
    assert qrt.used_by_rows_for(rows, [operator]) == [postgres]


def test_used_by_rows_for_no_match_returns_empty(qrt: ModuleType, rows):
    open_zaak = [rows[1]]
    assert qrt.used_by_rows_for(rows, open_zaak) == []


def test_used_by_rows_for_excludes_the_matches_themselves(qrt: ModuleType):
    """A matched row whose own used_by happens to substring-match its own
    name (e.g. a "Kiss ..." row with used_by "kiss") must not be echoed
    back as its own "used by" result."""
    self_referential = {
        "name": "Kiss Thing",
        "used_by": "kiss",
        "alias": "",
        "source_version_app": "1.0",
        "source_version_helm": "1.0",
        "target_version_app": "1.0",
        "target_version_helm": "1.0",
    }
    assert qrt.used_by_rows_for([self_referential], [self_referential]) == []


# --- component_matches ---


def test_component_matches_via_component_column(qrt: ModuleType, rows):
    matches = qrt.component_matches(rows, "zaakafhandelcomponent")
    assert [r["name"] for r in matches] == ["ZAC"]


def test_component_matches_via_alias_when_component_does_not_relate(qrt: ModuleType, rows):
    """ "zac" isn't a substring of component "zaakafhandelcomponent"
    itself, but it exactly equals that row's own "alias" — the alias
    column is tried before ever falling back to "name"."""
    matches = qrt.component_matches(rows, "zac")
    assert [r["name"] for r in matches] == ["ZAC"]


def test_component_matches_falls_back_to_name_when_neither_relates(qrt: ModuleType, rows):
    """ "Solr" has no resolved component or alias of its own at all —
    falls back to a plain "name" substring match so it can still be
    found, rather than returning nothing."""
    matches = qrt.component_matches(rows, "solr")
    assert [r["name"] for r in matches] == ["Solr"]


def test_component_matches_component_or_alias_hit_takes_priority_over_unrelated_name_hit(qrt: ModuleType, rows):
    """ "Contact (KISS)" resolves via its own component/alias ("kiss-chart"
    / "kiss") — once that's found, "name" is never consulted at all, so
    "Kiss Elastic Sync" (which only coincidentally contains "kiss" in its
    own name, but has no component/alias of its own) is correctly left
    out of the primary matches."""
    matches = qrt.component_matches(rows, "kiss")
    assert [r["name"] for r in matches] == ["Contact (KISS)"]


def test_component_matches_no_match_anywhere_is_empty(qrt: ModuleType, rows):
    assert qrt.component_matches(rows, "nonexistent") == []


# --- used_by_rows_for: alias path ---


def test_used_by_rows_for_resolves_used_by_via_alias_column(qrt: ModuleType, rows):
    """ "ita" isn't a substring of "Interne Taak Afhandeling" at all —
    only matching against that row's own "alias" column (set by
    export-confluence-release-table, resolved from Chart.yaml at
    export time) connects it back to ITA Poller."""
    interne_taak = [r for r in rows if r["name"] == "Interne Taak Afhandeling"]
    matches = qrt.used_by_rows_for(rows, interne_taak)
    assert [r["name"] for r in matches] == ["ITA Poller"]


def test_used_by_rows_for_blank_alias_misses_the_alias_path(qrt: ModuleType, rows):
    """A row with no "alias" set can't be connected to tooling that way —
    only the plain-substring rule (or an explicit alias) works."""
    some_component = [r for r in rows if r["name"] == "Some Component"]
    assert qrt.used_by_rows_for(rows, some_component) == []


# --- display_value ---


def test_display_value_target_empty_is_unchanged(qrt: ModuleType, rows):
    elastic = rows[2]
    assert qrt.display_value(elastic, "target_version_app") == "UNCHANGED"
    assert qrt.display_value(elastic, "target_version_helm") == "UNCHANGED"


def test_display_value_target_present_is_unaffected(qrt: ModuleType, rows):
    zac = rows[0]
    assert qrt.display_value(zac, "target_version_app") == "5.1.0"


def test_display_value_target_equal_to_source_is_unchanged(qrt: ModuleType, rows):
    """A non-empty target that's identical to its own source column (not
    exercised by the fixture rows, but a legitimate "no real change"
    case elsewhere in the pipeline — e.g. only the Helm chart version
    bumped, not the app version) shows UNCHANGED too, not the raw
    (unchanged) value."""
    zac = dict(rows[0])
    zac["target_version_app"] = zac["source_version_app"]
    assert qrt.display_value(zac, "target_version_app") == "UNCHANGED"


def test_display_value_source_empty_stays_empty_not_unchanged(qrt: ModuleType, rows):
    """UNCHANGED is only ever a target-column concept — see the module
    docstring — an empty source value (not exercised by the fixture rows,
    but a legitimate "no data" case elsewhere in the pipeline) must not be
    relabeled."""
    elastic = dict(rows[2])
    elastic["source_version_app"] = ""
    assert qrt.display_value(elastic, "source_version_app") == ""


# --- print_table ---


def test_print_table_aligns_columns_with_header(qrt: ModuleType, capsys: pytest.CaptureFixture[str], rows):
    qrt.print_table([rows[0]])
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("name")
    assert "5.0.0" in out[1]
    assert "5.1.0" in out[1]


def test_print_table_includes_image_basename(qrt: ModuleType, capsys: pytest.CaptureFixture[str], rows):
    """image_basename -- set by export-confluence-release-table's own
    resolve_image_basenames -- is shown alongside component/alias, not
    just usable for filtering. Uses a row whose image_basename ("kiss-
    frontend") is a distinct string from its own component ("kiss-chart"),
    so the assertion can't accidentally pass via the component column."""
    kiss = next(r for r in rows if r["name"] == "Contact (KISS)")
    qrt.print_table([kiss])
    out = capsys.readouterr().out.splitlines()
    assert "kiss-frontend" in out[1]


def test_print_table_includes_component_and_alias(qrt: ModuleType, capsys: pytest.CaptureFixture[str], rows):
    """component/alias — set by export-confluence-release-table — are
    shown alongside name and the version columns, not just usable for
    filtering."""
    ita = next(r for r in rows if r["name"] == "Interne Taak Afhandeling")
    qrt.print_table([ita])
    out = capsys.readouterr().out.splitlines()
    assert out[0].split() == [
        "name",
        "component",
        "alias",
        "image_basename",
        "source_version_app",
        "source_version_helm",
        "target_version_app",
        "target_version_helm",
    ]
    assert "internetaakafhandeling" in out[1]
    assert "ita" in out[1]


def test_print_table_shows_unchanged_for_empty_target(qrt: ModuleType, capsys: pytest.CaptureFixture[str], rows):
    qrt.print_table([rows[2]])
    out = capsys.readouterr().out
    assert "UNCHANGED" in out


# --- main ---


def run_main(qrt: ModuleType, monkeypatch: pytest.MonkeyPatch, csv_path, argv):
    monkeypatch.setattr(qrt, "DEFAULT_INPUT", csv_path)
    monkeypatch.setattr("sys.argv", ["query-release-table", *argv])


def test_main_prints_matches(
    qrt: ModuleType, monkeypatch: pytest.MonkeyPatch, csv_path, capsys: pytest.CaptureFixture[str]
):
    run_main(qrt, monkeypatch, csv_path, ["component", "zac"])
    qrt.main()
    out = capsys.readouterr().out
    assert "ZAC" in out
    assert "5.1.0" in out


def test_main_prints_heading_above_primary_matches(
    qrt: ModuleType, monkeypatch: pytest.MonkeyPatch, csv_path, capsys: pytest.CaptureFixture[str]
):
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


def test_main_component_query_also_shows_used_by_matches(
    qrt: ModuleType, monkeypatch: pytest.MonkeyPatch, csv_path, capsys: pytest.CaptureFixture[str]
):
    run_main(qrt, monkeypatch, csv_path, ["component", "zac"])
    qrt.main()
    out = capsys.readouterr().out
    assert "Used by matched component(s):" in out
    assert "Solr" in out
    assert "8.11.0" in out


def test_main_component_query_omits_used_by_section_when_no_matches(
    qrt: ModuleType, monkeypatch: pytest.MonkeyPatch, csv_path, capsys: pytest.CaptureFixture[str]
):
    run_main(qrt, monkeypatch, csv_path, ["component", "open zaak"])
    qrt.main()
    out = capsys.readouterr().out
    assert "Used by" not in out


def test_main_vendor_query_also_shows_used_by_matches(
    qrt: ModuleType, monkeypatch: pytest.MonkeyPatch, csv_path, capsys: pytest.CaptureFixture[str]
):
    """Querying vendor "info" matches name "ZAC" — since "zac" (a
    Technische row's used_by) is contained in that name, Solr
    must show up too, even though the query itself never touched
    "name" or the text "zac"."""
    run_main(qrt, monkeypatch, csv_path, ["vendor", "info"])
    qrt.main()
    out = capsys.readouterr().out
    assert "Used by matched component(s):" in out
    assert "Solr" in out


def test_main_vendor_query_omits_used_by_section_when_unrelated(
    qrt: ModuleType, monkeypatch: pytest.MonkeyPatch, csv_path, capsys: pytest.CaptureFixture[str]
):
    """Vendor "Maykin" only matches "Open Zaak" — unrelated to any
    used_by value in the fixture, so no used_by section at all."""
    run_main(qrt, monkeypatch, csv_path, ["vendor", "maykin"])
    qrt.main()
    out = capsys.readouterr().out
    assert "Open Zaak" in out
    assert "Used by" not in out


def test_main_resolves_used_by_via_alias_column(
    qrt: ModuleType, monkeypatch: pytest.MonkeyPatch, csv_path, capsys: pytest.CaptureFixture[str]
):
    """End-to-end: querying "Interne Taak Afhandeling" pulls in "ITA
    Poller" via its own "alias" column, already baked into the CSV by
    export-confluence-release-table — no Chart.yaml needed at query
    time. Neither its component nor alias contains "interne taak", so
    this falls all the way through component_matches to the "name"
    last resort."""
    run_main(qrt, monkeypatch, csv_path, ["component", "interne taak"])
    qrt.main()
    out = capsys.readouterr().out
    assert "Used by matched component(s):" in out
    assert "ITA Poller" in out


def test_main_component_query_by_alias_shows_owner_as_sole_primary_match(
    qrt: ModuleType, monkeypatch: pytest.MonkeyPatch, csv_path, capsys: pytest.CaptureFixture[str]
):
    """Querying component "ita" resolves to "Interne Taak Afhandeling"
    itself via its own "alias" column — that's the sole primary match,
    found before "name" is ever consulted. "ITA Poller" (which also
    contains "ita" literally in its own name) is tooling belonging to
    it, not a primary match in its own right — see component_matches."""
    run_main(qrt, monkeypatch, csv_path, ["component", "ita"])
    qrt.main()
    out = capsys.readouterr().out
    matches_section = out.split("Used by matched component(s):")[0]
    assert "Interne Taak Afhandeling" in matches_section
    assert "ITA Poller" not in matches_section


def test_main_component_query_by_alias_shows_tooling_in_used_by_exactly_once(
    qrt: ModuleType, monkeypatch: pytest.MonkeyPatch, csv_path, capsys: pytest.CaptureFixture[str]
):
    run_main(qrt, monkeypatch, csv_path, ["component", "ita"])
    qrt.main()
    out = capsys.readouterr().out
    assert "Used by matched component(s):" in out
    assert out.count("ITA Poller") == 1


def test_main_component_query_kiss_one_owner_match_rest_in_used_by(
    qrt: ModuleType, monkeypatch: pytest.MonkeyPatch, csv_path, capsys: pytest.CaptureFixture[str]
):
    """ "Contact (KISS)" resolves via its own component/alias
    ("kiss-chart" / "kiss") and is the sole primary match; "Kiss Elastic
    Sync" and "PodiumD Adapter" (which only coincidentally contain
    "kiss", or have it as used_by) are its tooling and belong in the
    used_by table instead."""
    run_main(qrt, monkeypatch, csv_path, ["component", "kiss"])
    qrt.main()
    out = capsys.readouterr().out
    matches_section, _, used_by_section = out.partition("Used by matched component(s):")
    assert "Contact (KISS)" in matches_section
    assert "Kiss Elastic Sync" not in matches_section
    assert "PodiumD Adapter" not in matches_section
    assert "Kiss Elastic Sync" in used_by_section
    assert "PodiumD Adapter" in used_by_section


def test_main_no_matches_exits_nonzero(
    qrt: ModuleType, monkeypatch: pytest.MonkeyPatch, csv_path, capsys: pytest.CaptureFixture[str]
):
    run_main(qrt, monkeypatch, csv_path, ["component", "nonexistent"])
    with pytest.raises(SystemExit) as exc_info:
        qrt.main()
    assert exc_info.value.code != 0
    assert "no rows found" in capsys.readouterr().out


@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_main_help_flag_prints_usage_and_exits_zero(
    qrt: ModuleType, monkeypatch: pytest.MonkeyPatch, csv_path, capsys: pytest.CaptureFixture[str], flag
):
    run_main(qrt, monkeypatch, csv_path, [flag])
    with pytest.raises(SystemExit) as exc_info:
        qrt.main()
    assert exc_info.value.code == 0
    assert capsys.readouterr().out == f"{qrt.__doc__}\n"


def test_main_invalid_column_prints_usage(
    qrt: ModuleType, monkeypatch: pytest.MonkeyPatch, csv_path, capsys: pytest.CaptureFixture[str]
):
    run_main(qrt, monkeypatch, csv_path, ["bogus", "zac"])
    with pytest.raises(SystemExit) as exc_info:
        qrt.main()
    assert exc_info.value.code != 0
    assert "Usage:" in capsys.readouterr().out


def test_main_name_is_no_longer_a_valid_column(
    qrt: ModuleType, monkeypatch: pytest.MonkeyPatch, csv_path, capsys: pytest.CaptureFixture[str]
):
    """ "name" was removed as a directly queryable column — component
    now covers that ground itself, falling back to name internally (see
    component_matches) rather than exposing it as its own query mode."""
    run_main(qrt, monkeypatch, csv_path, ["name", "zac"])
    with pytest.raises(SystemExit) as exc_info:
        qrt.main()
    assert exc_info.value.code != 0
    assert "Usage:" in capsys.readouterr().out


def test_main_wrong_arg_count_prints_usage(
    qrt: ModuleType, monkeypatch: pytest.MonkeyPatch, csv_path, capsys: pytest.CaptureFixture[str]
):
    run_main(qrt, monkeypatch, csv_path, ["component"])
    with pytest.raises(SystemExit) as exc_info:
        qrt.main()
    assert exc_info.value.code != 0
    assert "Usage:" in capsys.readouterr().out


def test_main_missing_input_file_errors(
    qrt: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    missing = tmp_path / "does-not-exist.csv"
    monkeypatch.setattr(qrt, "DEFAULT_INPUT", missing)
    monkeypatch.setattr("sys.argv", ["query-release-table", "component", "zac"])
    with pytest.raises(SystemExit) as exc_info:
        qrt.main()
    assert exc_info.value.code != 0
    out = capsys.readouterr().out
    assert "not found" in out
    assert "export-confluence-release-table" in out
