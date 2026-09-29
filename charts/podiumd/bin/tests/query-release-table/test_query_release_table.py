"""query-release-table, with DEFAULT_INPUT pointed at a fixture CSV."""

from pathlib import Path
from types import ModuleType

import pytest

from lib.release_table.csv_rows import read_release_table

CSV_TEXT = """\
section,vendor,used_by,name,component,alias,image_basename,source_version_app,source_version_helm,target_version_app,target_version_helm
Product,Info(NL),,ZAC,zaakafhandelcomponent,zac,zaakafhandelcomponent,5.0.0,1.0.290,5.1.0,1.0.297
Product,Maykin,,Open Zaak,openzaak,,,1.27.0,1.14.0,1.27.4,1.14.2
Technische,,,Elastic operator,,,,3.4.0,3.4.0,,
Technische,,zac,Solr,zaakafhandelcomponent,zac,solr,8.11.0,8.11.0,8.11.0,8.11.0
Product,ZAC Team,,Some Component,,,,1.0.0,1.0.0,1.0.0,1.0.0
Product,ICATT,,Interne Taak Afhandeling,internetaakafhandeling,ita,,3.2.0,3.2.0,3.3.0,3.3.0
Technische,,ita,ITA Poller,internetaakafhandeling,ita,,1.0.0,1.0.0,1.0.0,1.0.0
Product,ICATT,,Contact (KISS),kiss-chart,kiss,kiss-frontend,2.2.3,2.2.3,3.0.0,3.0.0
Technische,,kiss,Kiss Elastic Sync,kiss-chart,kiss,kiss-elastic-sync,0.3.3,0.3.3,3.0.0,3.0.0
Technische,,kiss,PodiumD Adapter,kiss-chart,kiss,podiumd-adapter,0.6.6,0.6.6,0.6.7,0.6.7
Overige,,,Keycloak,keycloak,,keycloak,26.6.4,NATIVE,26.7.3,NATIVE
Overige,,,Keycloak operator,keycloak-operator,,keycloak-operator,26.6.4,1.12.1,26.7.3,1.13.0
Technische,,keycloak-operator,Python,keycloak-operator,,python,3.14-slim,,3.14.7-slim,
Technische,,keycloak,Keycloak Config CLI,keycloak,,keycloak-config-cli,6.5.1-26,,6.5.1-26.5.5,
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
    assert len(rows) == 14
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


def test_used_by_rows_for_finds_tooling_of_the_matched_component(qrt: ModuleType, rows):
    """Tooling rows are found via their used_by matching the matched row's
    component, so a query on any column pulls them in."""
    zac = [rows[0]]
    assert [r["name"] for r in qrt.used_by_rows_for(rows, zac)] == ["Solr"]


def test_used_by_rows_for_uses_the_exported_component_not_name_words(qrt: ModuleType, rows) -> None:
    """Keycloak Config CLI belongs to native keycloak, not "Keycloak operator",
    despite the whole-word match."""
    operator = [r for r in rows if r["name"] == "Keycloak operator"]
    keycloak = [r for r in rows if r["name"] == "Keycloak"]
    assert [r["name"] for r in qrt.used_by_rows_for(rows, operator)] == ["Python"]
    assert [r["name"] for r in qrt.used_by_rows_for(rows, keycloak)] == ["Keycloak Config CLI"]


def test_used_by_rows_for_no_match_returns_empty(qrt: ModuleType, rows):
    open_zaak = [rows[1]]
    assert qrt.used_by_rows_for(rows, open_zaak) == []


def test_used_by_rows_for_excludes_the_matches_themselves(qrt: ModuleType):
    """A tooling row that is itself a match is not repeated as "used by"."""
    tooling = {
        "name": "Kiss Thing",
        "used_by": "kiss",
        "component": "kiss-chart",
        "alias": "kiss",
        "source_version_app": "1.0",
        "source_version_helm": "1.0",
        "target_version_app": "1.0",
        "target_version_helm": "1.0",
    }
    assert qrt.used_by_rows_for([tooling], [tooling]) == []


def test_component_matches_via_component_column(qrt: ModuleType, rows):
    matches = qrt.component_matches(rows, "zaakafhandelcomponent")
    assert [r["name"] for r in matches] == ["ZAC"]


def test_component_matches_via_alias_when_component_does_not_relate(qrt: ModuleType, rows):
    """The alias column is tried before falling back to "name"."""
    matches = qrt.component_matches(rows, "zac")
    assert [r["name"] for r in matches] == ["ZAC"]


def test_component_matches_falls_back_to_name_when_neither_relates(qrt: ModuleType, rows):
    """Without component or alias, fall back to a "name" substring match."""
    matches = qrt.component_matches(rows, "solr")
    assert [r["name"] for r in matches] == ["Solr"]


def test_component_matches_component_or_alias_hit_takes_priority_over_unrelated_name_hit(qrt: ModuleType, rows):
    """Once component/alias matches, "name" is not consulted, so rows merely
    containing "kiss" in their name are not primary matches."""
    matches = qrt.component_matches(rows, "kiss")
    assert [r["name"] for r in matches] == ["Contact (KISS)"]


def test_component_matches_no_match_anywhere_is_empty(qrt: ModuleType, rows):
    assert qrt.component_matches(rows, "nonexistent") == []


# --- used_by_rows_for: exported component column ---


def test_used_by_rows_for_resolves_used_by_via_component_column(qrt: ModuleType, rows):
    """The shared exported "component" column links ITA Poller to its parent."""
    interne_taak = [r for r in rows if r["name"] == "Interne Taak Afhandeling"]
    matches = qrt.used_by_rows_for(rows, interne_taak)
    assert [r["name"] for r in matches] == ["ITA Poller"]


def test_used_by_rows_for_blank_component_pulls_in_nothing(qrt: ModuleType, rows):
    """A match with blank "component" has no tooling rows to connect."""
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
    """A target identical to its source shows UNCHANGED too (e.g. only the
    Helm chart version bumped)."""
    zac = dict(rows[0])
    zac["target_version_app"] = zac["source_version_app"]
    assert qrt.display_value(zac, "target_version_app") == "UNCHANGED"


def test_display_value_source_empty_stays_empty_not_unchanged(qrt: ModuleType, rows):
    """UNCHANGED is only a target-column concept: an empty source isn't relabeled."""
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
    """image_basename is shown; the fixture row's basename differs from its
    component so the assertion can't pass via the component column."""
    kiss = next(r for r in rows if r["name"] == "Contact (KISS)")
    qrt.print_table([kiss])
    out = capsys.readouterr().out.splitlines()
    assert "kiss-frontend" in out[1]


def test_print_table_includes_component_and_alias(qrt: ModuleType, capsys: pytest.CaptureFixture[str], rows):
    """component/alias are shown, not just usable for filtering."""
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
    """Primary matches get their own heading so a single row isn't read as
    part of the used_by section below."""
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
    """A tooling row of a matched row's component shows up even when the
    query never touched "component"."""
    run_main(qrt, monkeypatch, csv_path, ["vendor", "info"])
    qrt.main()
    out = capsys.readouterr().out
    assert "Used by matched component(s):" in out
    assert "Solr" in out


def test_main_vendor_query_omits_used_by_section_when_unrelated(
    qrt: ModuleType, monkeypatch: pytest.MonkeyPatch, csv_path, capsys: pytest.CaptureFixture[str]
):
    """A match unrelated to any used_by value prints no used_by section."""
    run_main(qrt, monkeypatch, csv_path, ["vendor", "maykin"])
    qrt.main()
    out = capsys.readouterr().out
    assert "Open Zaak" in out
    assert "Used by" not in out


def test_main_resolves_used_by_via_component_column(
    qrt: ModuleType, monkeypatch: pytest.MonkeyPatch, csv_path, capsys: pytest.CaptureFixture[str]
):
    """The CSV's "component" column links ITA Poller at query time without
    Chart.yaml, after falling through to the "name" last resort."""
    run_main(qrt, monkeypatch, csv_path, ["component", "interne taak"])
    qrt.main()
    out = capsys.readouterr().out
    assert "Used by matched component(s):" in out
    assert "ITA Poller" in out


def test_main_component_query_by_alias_shows_owner_as_sole_primary_match(
    qrt: ModuleType, monkeypatch: pytest.MonkeyPatch, csv_path, capsys: pytest.CaptureFixture[str]
):
    """An alias match is the sole primary match; ITA Poller, which also
    contains "ita", is its tooling, not a primary match."""
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
    """Rows sharing component/alias but with used_by "kiss" are tooling, listed
    under used_by, not primary matches."""
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
    """ "name" is not a queryable column; component falls back to it internally."""
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


def test_main_component_query_keycloak_operator_lists_only_its_own_tooling(
    qrt: ModuleType, monkeypatch: pytest.MonkeyPatch, csv_path, capsys: pytest.CaptureFixture[str]
):
    """ "keycloak-operator" matches only its own row; native keycloak's
    Config CLI appears nowhere."""
    run_main(qrt, monkeypatch, csv_path, ["component", "keycloak-operator"])
    qrt.main()
    out = capsys.readouterr().out
    matches_section, _, used_by_section = out.partition("Used by matched component(s):")
    assert "Keycloak operator" in matches_section
    assert "Python" not in matches_section
    assert "Python" in used_by_section
    assert "Keycloak Config CLI" not in out
