"""friendly_vendor_charts — classifies each Chart.yaml dependency as a
"friendly" vendor (Maykin, Info(NL), ICATT, Worth, WeAreFrank, Dimpact, or a
local file:// dependency) or leaves it unclassified (elastic,
redis-operator, keycloak-operator, openbao, ...). Used by
check_yamllint/check_kubeconform/check_shellcheck to decide which vendored
findings get per-item detail vs. an aggregate-count-only line."""


def write_chart_yaml(chart_dir, dependencies):
    import yaml
    (chart_dir / "Chart.yaml").write_text(
        yaml.safe_dump({"name": "podiumd", "version": "1.0.0", "dependencies": dependencies}),
        encoding="utf-8",
    )
    return chart_dir


def test_maykinmedia_repository_classified_as_maykin(vp, tmp_path):
    write_chart_yaml(tmp_path, [{"name": "openzaak", "version": "1.0.0", "repository": "@maykinmedia"}])
    assert vp.friendly_vendor_charts(tmp_path) == {"openzaak": "Maykin"}


def test_alias_used_as_chart_name_not_dependency_name(vp, tmp_path):
    """Helm names the charts/<name>/ directory (and so the "# Source:"
    path) after the alias when one is set — the mapping must key off that,
    not the underlying dependency name."""
    write_chart_yaml(tmp_path, [
        {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.0", "repository": "@zac"},
    ])
    result = vp.friendly_vendor_charts(tmp_path)
    assert result == {"zac": "Info(NL)"}
    assert "zaakafhandelcomponent" not in result


def test_at_alias_repository_resolved_via_required_repos(vp, tmp_path):
    """"@zac" itself doesn't contain "infonl" — only REQUIRED_REPOS'
    resolved URL (https://infonl.github.io/dimpact-zaakafhandelcomponent/)
    does, so resolution must happen before keyword matching."""
    assert "infonl" not in "@zac"
    assert "zac" in vp.REQUIRED_REPOS
    assert "infonl" in vp.REQUIRED_REPOS["zac"].lower()
    write_chart_yaml(tmp_path, [
        {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.0", "repository": "@zac"},
    ])
    assert vp.friendly_vendor_charts(tmp_path)["zac"] == "Info(NL)"


def test_worth_nl_repository_classified_as_worth(vp, tmp_path):
    write_chart_yaml(tmp_path, [
        {"name": "notifynl-omc-nodep", "alias": "omc", "version": "1.0.0", "repository": "@worth-nl"},
    ])
    assert vp.friendly_vendor_charts(tmp_path) == {"omc": "Worth"}


def test_wearefrank_literal_url_classified_as_wearefrank(vp, tmp_path):
    write_chart_yaml(tmp_path, [
        {"name": "zaakbrug", "version": "1.0.0", "repository": "https://wearefrank.github.io/charts"},
    ])
    assert vp.friendly_vendor_charts(tmp_path) == {"zaakbrug": "WeAreFrank"}


def test_dimpact_alias_classified_as_dimpact(vp, tmp_path):
    write_chart_yaml(tmp_path, [
        {"name": "brp-personen-mock", "alias": "brppersonenmock", "version": "1.0.0", "repository": "@dimpact"},
    ])
    assert vp.friendly_vendor_charts(tmp_path) == {"brppersonenmock": "Dimpact"}


def test_kiss_chart_overridden_to_icatt_despite_unmatching_repository(vp, tmp_path):
    """kiss-chart's own repository (oci://ghcr.io/klantinteractie-servicesysteem)
    contains none of the FRIENDLY_VENDOR_KEYWORDS — ICATT authorship can
    only be known from docs, so it's a hardcoded override."""
    write_chart_yaml(tmp_path, [
        {"name": "kiss-chart", "alias": "kiss", "version": "1.0.0",
         "repository": "oci://ghcr.io/klantinteractie-servicesysteem"},
    ])
    assert vp.friendly_vendor_charts(tmp_path) == {"kiss": "ICATT"}


def test_local_file_dependency_classified_as_local(vp, tmp_path):
    write_chart_yaml(tmp_path, [
        {"name": "mi-data", "alias": "mi", "version": "1.0.0", "repository": "file://../mi-data"},
    ])
    assert vp.friendly_vendor_charts(tmp_path) == {"mi": "Local"}


def test_unrelated_vendor_not_classified(vp, tmp_path):
    write_chart_yaml(tmp_path, [
        {"name": "redis-operator", "version": "1.0.0", "repository": "@opstree"},
        {"name": "openbao", "version": "1.0.0", "repository": "https://openbao.github.io/openbao-helm"},
    ])
    assert vp.friendly_vendor_charts(tmp_path) == {}


def test_full_real_dependency_set_matches_expected_mapping(vp, tmp_path):
    """Regression pin against the actual set of Chart.yaml dependencies
    known at the time this was written — catches an accidental keyword/
    override change breaking a previously-classified chart."""
    write_chart_yaml(tmp_path, [
        {"name": "keycloak-operator", "version": "1.0.0", "repository": "@adfinis"},
        {"name": "clamav", "version": "1.0.0", "repository": "@wiremind"},
        {"name": "brp-personen-mock", "alias": "brppersonenmock", "version": "1.0.0", "repository": "@dimpact"},
        {"name": "mi-data", "alias": "mi", "version": "1.0.0", "repository": "file://../mi-data"},
        {"name": "openzaak", "version": "1.0.0", "repository": "@maykinmedia"},
        {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.0", "repository": "@zac"},
        {"name": "zaakbrug", "version": "1.0.0", "repository": "https://wearefrank.github.io/charts"},
        {"name": "zgw-office-addin", "version": "1.0.0", "repository": "@zgw-office-addin"},
        {"name": "internetaakafhandeling", "alias": "ita", "version": "1.0.0",
         "repository": "oci://ghcr.io/interne-taak-afhandeling"},
        {"name": "kiss-chart", "alias": "kiss", "version": "1.0.0",
         "repository": "oci://ghcr.io/klantinteractie-servicesysteem"},
        {"name": "pabc", "version": "1.0.0", "repository": "oci://ghcr.io/platform-autorisatie-beheer-component"},
        {"name": "notifynl-omc-nodep", "alias": "omc", "version": "1.0.0", "repository": "@worth-nl"},
        {"name": "redis-operator", "version": "1.0.0", "repository": "@opstree"},
        {"name": "eck-operator", "version": "1.0.0", "repository": "https://helm.elastic.co"},
        {"name": "openbao", "version": "1.0.0", "repository": "https://openbao.github.io/openbao-helm"},
    ])
    assert vp.friendly_vendor_charts(tmp_path) == {
        "brppersonenmock": "Dimpact",
        "mi": "Local",
        "openzaak": "Maykin",
        "zac": "Info(NL)",
        "zaakbrug": "WeAreFrank",
        "zgw-office-addin": "Info(NL)",
        "kiss": "ICATT",
        "omc": "Worth",
    }
    # deliberately NOT classified — not in FRIENDLY_VENDOR_KEYWORDS/OVERRIDES
    for unclassified in ("keycloak-operator", "clamav", "ita", "pabc", "redis-operator", "eck-operator", "openbao"):
        assert unclassified not in vp.friendly_vendor_charts(tmp_path)
