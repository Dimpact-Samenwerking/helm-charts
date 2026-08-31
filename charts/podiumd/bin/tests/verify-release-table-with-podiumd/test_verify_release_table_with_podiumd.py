"""compare() (the pure comparison core) and main() for
verify-release-table-with-podiumd. compare() takes plain in-memory
deps/values/lines/rows, so these tests need neither a real Chart.yaml nor
network access; main()'s own tests just cover its file-loading/CLI glue."""
import pytest

DIGEST = "a" * 64


def csv_row(name, component, alias="", image_basename="", source_app="", source_helm="",
            target_app="", target_helm=""):
    return {
        "section": "Product", "vendor": "", "used_by": "", "name": name, "component": component,
        "alias": alias, "image_basename": image_basename, "source_version_app": source_app,
        "source_version_helm": source_helm, "target_version_app": target_app, "target_version_helm": target_helm,
    }


def values_lines(*blocks):
    return "\n".join(blocks).splitlines()


ZAC_BLOCK = (
    "zac:\n"
    "  image:\n"
    "    repository: ghcr.io/infonl/zaakafhandelcomponent\n"
    f'    tag: "5.4.3@sha256:{DIGEST}"\n'
)


# --- compare(): version mismatches ---

def test_compare_reports_chart_version_mismatch(vrt):
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    rows = [csv_row("Zaak - ZAC", "zaakafhandelcomponent", alias="zac", image_basename="zaakafhandelcomponent",
                     target_app="5.4.3", target_helm="1.0.298")]
    findings, unresolved = vrt.compare(rows, deps, {}, values_lines(ZAC_BLOCK))
    assert any("target 1.0.298 != Chart.yaml 1.0.297" in m for m in findings["mismatches"])
    assert unresolved == []


def test_compare_reports_image_version_mismatch(vrt):
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    rows = [csv_row("Zaak - ZAC", "zaakafhandelcomponent", alias="zac", image_basename="zaakafhandelcomponent",
                     target_app="5.4.4", target_helm="1.0.297")]
    findings, _ = vrt.compare(rows, deps, {}, values_lines(ZAC_BLOCK))
    assert any("target 5.4.4 != values.yaml 5.4.3" in m for m in findings["mismatches"])


def test_compare_no_findings_when_everything_matches(vrt):
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    rows = [csv_row("Zaak - ZAC", "zaakafhandelcomponent", alias="zac", image_basename="zaakafhandelcomponent",
                     target_app="5.4.3", target_helm="1.0.297")]
    findings, unresolved = vrt.compare(rows, deps, {}, values_lines(ZAC_BLOCK))
    assert findings == {}
    assert unresolved == []


@pytest.mark.parametrize("target_app,target_helm", [("", ""), ("UNKNOWN", "UNKNOWN")])
def test_compare_skips_blank_or_unknown_targets(vrt, target_app, target_helm):
    """A blank/UNKNOWN target means "nothing planned to compare" (see
    query-release-table's own UNCHANGED display logic) — not a
    mismatch just because it differs textually from the actual version."""
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    rows = [csv_row("Zaak - ZAC", "zaakafhandelcomponent", alias="zac", image_basename="zaakafhandelcomponent",
                     target_app=target_app, target_helm=target_helm)]
    findings, _ = vrt.compare(rows, deps, {}, values_lines(ZAC_BLOCK))
    assert findings == {}


# --- compare(): missing from release-table.csv ---

def test_compare_reports_dependency_with_no_release_table_row(vrt):
    deps = [{"name": "openklant", "alias": "", "version": "1.11.0"}]
    findings, _ = vrt.compare([], deps, {}, [])
    assert any("Chart.yaml dependency 'openklant'" in m for m in findings["missing_from_release_table"])


def test_compare_reports_image_pinned_but_not_tracked(vrt):
    """values.yaml pins an image under zac's own scope that no
    release-table.csv row mentions at all."""
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    rows = [csv_row("Zaak - ZAC", "zaakafhandelcomponent", alias="zac", image_basename="",
                     target_helm="1.0.297")]
    findings, _ = vrt.compare(rows, deps, {}, values_lines(ZAC_BLOCK))
    assert any("'zaakafhandelcomponent' is pinned in values.yaml but not tracked" in m
               for m in findings["missing_from_release_table"])


# --- compare(): missing from Chart.yaml / values.yaml ---

def test_compare_reports_row_component_no_longer_a_dependency(vrt):
    rows = [csv_row("Long Gone", "longgone")]
    findings, _ = vrt.compare(rows, [], {}, [])
    assert any("resolves to component 'longgone', which is not a Chart.yaml dependency" in m
               for m in findings["missing_from_chart"])


def test_compare_reports_tracked_image_no_longer_pinned(vrt):
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    rows = [csv_row("Zaak - ZAC", "zaakafhandelcomponent", alias="zac", image_basename="zaakafhandelcomponent",
                     target_helm="1.0.297"),
            csv_row("Zaak - ZAC OPA", "zaakafhandelcomponent", alias="zac", image_basename="opa",
                     target_app="1.17.1", target_helm="1.0.297")]
    findings, _ = vrt.compare(rows, deps, {}, values_lines(ZAC_BLOCK))
    assert any("release-table image 'opa' for component 'zaakafhandelcomponent'" in m
               for m in findings["missing_from_chart"])


# --- compare(): orphan components (no separate Chart.yaml dependency) ---

def test_compare_checks_images_for_orphan_values_yaml_component(vrt):
    """frankgateway-style: no Chart.yaml dependency, but a real top-level
    values.yaml key — its own image(s) are still checked, just without a
    chart-version comparison (no Chart.yaml "version:" to compare against)."""
    frank_block = (
        "frankgateway:\n"
        "  image:\n"
        "    repository: ghcr.io/wearefrank/frank-gateway\n"
        f'    tag: "1.1.0@sha256:{DIGEST}"\n'
    )
    rows = [csv_row("Frank Gateway", "frankgateway", image_basename="frank-gateway", target_app="1.1.1")]
    findings, unresolved = vrt.compare(rows, [], {"frankgateway": {}}, values_lines(frank_block))
    assert any("target 1.1.1 != values.yaml 1.1.0" in m for m in findings["mismatches"])
    assert "missing_from_chart" not in findings
    assert unresolved == []


def test_compare_orphan_component_absent_from_values_yaml_is_missing_from_chart(vrt):
    rows = [csv_row("Frank Gateway", "frankgateway")]
    findings, _ = vrt.compare(rows, [], {}, [])
    assert any("component 'frankgateway'" in m for m in findings["missing_from_chart"])


# --- compare(): ambiguous pins ---

def test_compare_reports_ambiguous_when_basename_pinned_at_multiple_versions(vrt):
    block = (
        "zac:\n"
        "  a:\n"
        "    image:\n"
        "      repository: docker.io/curlimages/curl\n"
        f'      tag: "8.21.0@sha256:{"a" * 64}"\n'
        "  b:\n"
        "    image:\n"
        "      repository: docker.io/curlimages/curl\n"
        f'      tag: "8.22.0@sha256:{"b" * 64}"\n'
    )
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    rows = [csv_row("Zaak - ZAC", "zaakafhandelcomponent", alias="zac", image_basename="curl", target_app="8.22.0")]
    findings, _ = vrt.compare(rows, deps, {}, values_lines(block))
    assert any("pinned at 2 different versions" in m for m in findings["ambiguous"])
    assert "mismatches" not in findings


# --- compare(): unresolved components ---

@pytest.mark.parametrize("component", ["", "UNKNOWN"])
def test_compare_lists_unresolved_rows_separately(vrt, component):
    rows = [csv_row("Solr", component)]
    findings, unresolved = vrt.compare(rows, [], {}, [])
    assert findings == {}
    assert unresolved == rows


# --- compare(): MULTIPLE (global.images) rows ---

GLOBAL_CURL_BLOCK = (
    "global:\n"
    "  images:\n"
    "    curl:\n"
    "      repository: docker.io/curlimages/curl\n"
    f'      tag: "8.22.0@sha256:{DIGEST}"\n'
)


def test_compare_checks_multiple_row_against_global_images(vrt):
    """A "MULTIPLE" row (a shared base image like curl, hoisted into
    values.yaml's global.images map) is checked against the "global"
    scope, not skipped as unresolved."""
    rows = [csv_row("Curl", "MULTIPLE", alias="MULTIPLE", image_basename="curl", target_app="8.23.0")]
    findings, unresolved = vrt.compare(rows, [], {}, values_lines(GLOBAL_CURL_BLOCK))
    assert any("target 8.23.0 != values.yaml 8.22.0" in m for m in findings["mismatches"])
    assert unresolved == []


def test_compare_multiple_row_matching_global_image_passes(vrt):
    rows = [csv_row("Curl", "MULTIPLE", alias="MULTIPLE", image_basename="curl", target_app="8.22.0")]
    findings, unresolved = vrt.compare(rows, [], {}, values_lines(GLOBAL_CURL_BLOCK))
    assert findings == {}
    assert unresolved == []


def test_compare_multiple_row_with_no_image_basename_is_silently_skipped(vrt):
    """A "MULTIPLE" row export-confluence-release-table couldn't even
    resolve an image_basename for (an ambiguous plain dependency-name
    collision, not a global image) has nothing to check — not an error."""
    rows = [csv_row("Something Ambiguous", "MULTIPLE", alias="MULTIPLE", image_basename="")]
    findings, unresolved = vrt.compare(rows, [], {}, [])
    assert findings == {}
    assert unresolved == []


def test_compare_reports_global_image_with_no_release_table_row(vrt):
    findings, _ = vrt.compare([], [], {}, values_lines(GLOBAL_CURL_BLOCK))
    assert any("'global' image 'curl' is pinned in values.yaml but not tracked" in m
               for m in findings["missing_from_release_table"])


# --- multi-image component (e.g. zgw-office-addin) ---

def test_compare_multi_image_component_checks_every_basename(vrt):
    block = (
        "zgw-office-addin:\n"
        "  frontend:\n"
        "    image:\n"
        "      repository: ghcr.io/infonl/zgw-office-addin-frontend\n"
        f'      tag: "0.11.0@sha256:{"a" * 64}"\n'
        "  backend:\n"
        "    image:\n"
        "      repository: ghcr.io/infonl/zgw-office-addin-backend\n"
        f'      tag: "0.11.0@sha256:{"b" * 64}"\n'
    )
    deps = [{"name": "zgw-office-addin", "alias": "", "version": "0.0.92"}]
    rows = [csv_row("Office Add-in", "zgw-office-addin",
                     image_basename="zgw-office-addin-frontend,zgw-office-addin-backend",
                     target_app="0.12.0", target_helm="0.0.92")]
    findings, _ = vrt.compare(rows, deps, {}, values_lines(block))
    assert len(findings["mismatches"]) == 2
    assert any("zgw-office-addin-frontend" in m for m in findings["mismatches"])
    assert any("zgw-office-addin-backend" in m for m in findings["mismatches"])


# --- compare(): special-case images (not seen by the normal digest-pin scan) ---

def keycloak_values(tag="26.7.2"):
    return {"keycloak-operator": {"operator": {"config": {"keycloakImage": {
        "repository": "quay.io/keycloak/keycloak", "tag": tag, "sha": "deadbeef",
    }}}}}


def test_compare_checks_keycloak_special_case_image(vrt):
    """keycloak-operator's own actual Keycloak SERVER image lives as a
    split "tag:"/"sha:" field pair, not a plain "image:" block — invisible
    to the normal digest-pin scan regardless of scope, so its plain tag is
    read directly instead (see SPECIAL_CASE_BASENAME_TAG_PATHS)."""
    deps = [{"name": "keycloak-operator", "alias": "", "version": "1.12.1"}]
    rows = [csv_row("Keycloak", "keycloak-operator", image_basename="keycloak", target_app="26.7.3")]
    findings, _ = vrt.compare(rows, deps, keycloak_values(), [])
    assert any("target 26.7.3 != values.yaml 26.7.2" in m for m in findings["mismatches"])
    assert "missing_from_chart" not in findings


def test_compare_keycloak_special_case_image_matching_passes(vrt):
    deps = [{"name": "keycloak-operator", "alias": "", "version": "1.12.1"}]
    rows = [csv_row("Keycloak", "keycloak-operator", image_basename="keycloak", target_app="26.7.2")]
    findings, _ = vrt.compare(rows, deps, keycloak_values(), [])
    assert findings == {}


def test_compare_finds_basename_pinned_under_a_sibling_scope(vrt):
    """keycloak-config-cli lives under top-level "keycloak" (a values.yaml
    sibling block, separate from keycloak-operator's own scope) — a
    basename is a real repository identity, not a values.yaml path, so it
    can be pinned somewhere other than its own component's scope. Found
    via the same whole-file find_matches fallback update-image-version's
    own <target> resolution uses (lib.image_version.resolve_basename)."""
    keycloak_config_cli_block = (
        "keycloak:\n"
        "  keycloakConfigCli:\n"
        "    image:\n"
        "      repository: adorsys/keycloak-config-cli\n"
        f'      tag: "6.5.1-26@sha256:{"c" * 64}"\n'
    )
    deps = [{"name": "keycloak-operator", "alias": "", "version": "1.12.1"}]
    rows = [csv_row("Keycloak Config CLI", "keycloak-operator", image_basename="keycloak-config-cli",
                     target_app="6.5.2-27")]
    findings, _ = vrt.compare(rows, deps, {}, values_lines(keycloak_config_cli_block))
    assert any("target 6.5.2-27 != values.yaml 6.5.1-26" in m for m in findings["mismatches"])
    assert "missing_from_chart" not in findings


def test_compare_sibling_scope_basename_matching_passes(vrt):
    keycloak_config_cli_block = (
        "keycloak:\n"
        "  keycloakConfigCli:\n"
        "    image:\n"
        "      repository: adorsys/keycloak-config-cli\n"
        f'      tag: "6.5.1-26@sha256:{"c" * 64}"\n'
    )
    deps = [{"name": "keycloak-operator", "alias": "", "version": "1.12.1"}]
    rows = [csv_row("Keycloak Config CLI", "keycloak-operator", image_basename="keycloak-config-cli",
                     target_app="6.5.1-26")]
    findings, _ = vrt.compare(rows, deps, {}, values_lines(keycloak_config_cli_block))
    assert findings == {}


def test_compare_checks_omc_special_case_image(vrt):
    """omc's own image tag intentionally carries no digest at all, so
    export-confluence-release-table never resolves an image_basename
    for its row (blank column) — checked here independently, keyed by
    component instead (see SPECIAL_CASE_COMPONENT_TAG_PATHS)."""
    deps = [{"name": "notifynl-omc-nodep", "alias": "omc", "version": "0.14.1"}]
    rows = [csv_row("OMC / Notify", "notifynl-omc-nodep", alias="omc", target_app="1.17.20", target_helm="0.14.1")]
    values = {"omc": {"image": {"tag": "1.17.19"}}}
    findings, _ = vrt.compare(rows, deps, values, [])
    assert any("target 1.17.20 != values.yaml 1.17.19" in m for m in findings["mismatches"])


def test_compare_omc_special_case_image_matching_passes(vrt):
    deps = [{"name": "notifynl-omc-nodep", "alias": "omc", "version": "0.14.1"}]
    rows = [csv_row("OMC / Notify", "notifynl-omc-nodep", alias="omc", target_app="1.17.19", target_helm="0.14.1")]
    values = {"omc": {"image": {"tag": "1.17.19"}}}
    findings, _ = vrt.compare(rows, deps, values, [])
    assert findings == {}


# --- print_report(): output is sorted per category ---

def test_print_report_sorts_findings_within_each_section(vrt, capsys):
    findings = {
        "mismatches": [
            "[IMAGE] Zulu (zulu): release-table target 1 != values.yaml 2",
            "[CHART] Alpha (alpha): release-table target 1 != Chart.yaml 2",
        ],
    }
    vrt.print_report(findings, [])
    lines = [l for l in capsys.readouterr().out.splitlines() if l.startswith("  [")]
    assert lines == [
        "  [CHART] Alpha (alpha): release-table target 1 != Chart.yaml 2",
        "  [IMAGE] Zulu (zulu): release-table target 1 != values.yaml 2",
    ]


def test_print_report_sorts_unresolved_rows_by_name(vrt, capsys):
    unresolved = [csv_row("Zulu", "UNKNOWN"), csv_row("Alpha", ""), csv_row("Mike", "UNKNOWN")]
    vrt.print_report({}, unresolved)
    lines = [l for l in capsys.readouterr().out.splitlines() if l.strip().startswith("- '")]
    assert lines == [
        "  - 'Alpha' (component=(blank))",
        "  - 'Mike' (component=UNKNOWN)",
        "  - 'Zulu' (component=UNKNOWN)",
    ]


# --- main() ---

def run_main(vrt, monkeypatch, argv):
    monkeypatch.setattr("sys.argv", ["verify-release-table-with-podiumd", *argv])
    with pytest.raises(SystemExit) as exc_info:
        vrt.main()
    return exc_info.value.code


def test_main_missing_release_table_csv_fails(vrt, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(vrt, "RELEASE_TABLE_CSV", tmp_path / "release-table.csv")
    code = run_main(vrt, monkeypatch, [])
    assert code == 1
    assert "not found" in capsys.readouterr().out


def test_main_exits_zero_when_everything_matches(vrt, tmp_path, monkeypatch, capsys):
    import csv as csv_module

    chart_yaml = tmp_path / "Chart.yaml"
    values_yaml = tmp_path / "values.yaml"
    release_table = tmp_path / "release-table.csv"

    chart_yaml.write_text(
        "dependencies:\n"
        "  - name: zaakafhandelcomponent\n"
        "    version: 1.0.297\n"
        "    alias: zac\n",
        encoding="utf-8",
    )
    values_yaml.write_text(ZAC_BLOCK, encoding="utf-8")
    with release_table.open("w", newline="", encoding="utf-8") as f:
        writer = csv_module.DictWriter(f, fieldnames=list(csv_row("x", "y").keys()))
        writer.writeheader()
        writer.writerow(csv_row("Zaak - ZAC", "zaakafhandelcomponent", alias="zac",
                                 image_basename="zaakafhandelcomponent", target_app="5.4.3", target_helm="1.0.297"))

    monkeypatch.setattr(vrt, "CHART_YAML", chart_yaml)
    monkeypatch.setattr(vrt, "VALUES_YAML", values_yaml)
    monkeypatch.setattr(vrt, "RELEASE_TABLE_CSV", release_table)

    code = run_main(vrt, monkeypatch, [])
    assert code == 0
    assert "OK: release-table.csv matches" in capsys.readouterr().out


def test_main_exits_one_when_mismatch_found(vrt, tmp_path, monkeypatch, capsys):
    import csv as csv_module

    chart_yaml = tmp_path / "Chart.yaml"
    values_yaml = tmp_path / "values.yaml"
    release_table = tmp_path / "release-table.csv"

    chart_yaml.write_text(
        "dependencies:\n"
        "  - name: zaakafhandelcomponent\n"
        "    version: 1.0.298\n"
        "    alias: zac\n",
        encoding="utf-8",
    )
    values_yaml.write_text(ZAC_BLOCK, encoding="utf-8")
    with release_table.open("w", newline="", encoding="utf-8") as f:
        writer = csv_module.DictWriter(f, fieldnames=list(csv_row("x", "y").keys()))
        writer.writeheader()
        writer.writerow(csv_row("Zaak - ZAC", "zaakafhandelcomponent", alias="zac",
                                 image_basename="zaakafhandelcomponent", target_app="5.4.3", target_helm="1.0.297"))

    monkeypatch.setattr(vrt, "CHART_YAML", chart_yaml)
    monkeypatch.setattr(vrt, "VALUES_YAML", values_yaml)
    monkeypatch.setattr(vrt, "RELEASE_TABLE_CSV", release_table)

    code = run_main(vrt, monkeypatch, [])
    assert code == 1
    out = capsys.readouterr().out
    assert "Version mismatches" in out
    assert "1.0.297 != Chart.yaml 1.0.298" in out


def test_main_requires_no_arguments(vrt, monkeypatch):
    code = run_main(vrt, monkeypatch, ["extra-arg"])
    assert code == 1


@pytest.mark.parametrize("flag", ["-h", "--help"])
def test_main_help_flag_prints_usage_and_exits_zero(vrt, monkeypatch, capsys, flag):
    code = run_main(vrt, monkeypatch, [flag])
    assert code == 0
    assert capsys.readouterr().out == vrt.__doc__ + "\n"
