"""friendly_vendor_charts: classify each Chart.yaml dependency as a friendly
vendor or unclassified, which decides per-item vs aggregate reporting."""

from pathlib import Path
from types import ModuleType


def write_chart_yaml(chart_dir, dependencies):
    import yaml

    (chart_dir / "Chart.yaml").write_text(
        yaml.safe_dump({"name": "podiumd", "version": "1.0.0", "dependencies": dependencies}),
        encoding="utf-8",
    )
    return chart_dir


def test_maykinmedia_repository_classified_as_maykin(vp: ModuleType, librenderscope: ModuleType, tmp_path: Path):
    write_chart_yaml(tmp_path, [{"name": "openzaak", "version": "1.0.0", "repository": "@maykinmedia"}])
    assert librenderscope.friendly_vendor_charts(tmp_path) == {"openzaak": "Maykin"}


def test_alias_used_as_chart_name_not_dependency_name(vp: ModuleType, librenderscope: ModuleType, tmp_path: Path):
    """Helm names the charts/<name>/ directory (and so the "# Source:"
    path) after the alias when one is set — the mapping must key off that,
    not the underlying dependency name."""
    write_chart_yaml(
        tmp_path,
        [
            {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.0", "repository": "@zac"},
        ],
    )
    result = librenderscope.friendly_vendor_charts(tmp_path)
    assert result == {"zac": "Info(NL)"}
    assert "zaakafhandelcomponent" not in result


def test_at_alias_repository_resolved_via_required_repos(librenderscope: ModuleType, tmp_path: Path):
    """ "@zac" has no vendor keyword; only its resolved URL does, so alias
    resolution must precede keyword matching (hard-coded default here)."""
    required_repos = librenderscope.helm_repos_urls_by_alias(tmp_path)
    assert "infonl" not in "@zac"
    assert "zac" in required_repos
    assert "infonl" in required_repos["zac"].lower()
    write_chart_yaml(
        tmp_path,
        [
            {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.0", "repository": "@zac"},
        ],
    )
    assert librenderscope.friendly_vendor_charts(tmp_path)["zac"] == "Info(NL)"


def test_worth_nl_repository_classified_as_worth(vp: ModuleType, librenderscope: ModuleType, tmp_path: Path):
    write_chart_yaml(
        tmp_path,
        [
            {"name": "notifynl-omc-nodep", "alias": "omc", "version": "1.0.0", "repository": "@worth-nl"},
        ],
    )
    assert librenderscope.friendly_vendor_charts(tmp_path) == {"omc": "Worth"}


def test_wearefrank_literal_url_classified_as_wearefrank(vp: ModuleType, librenderscope: ModuleType, tmp_path: Path):
    write_chart_yaml(
        tmp_path,
        [
            {"name": "zaakbrug", "version": "1.0.0", "repository": "https://wearefrank.github.io/charts"},
        ],
    )
    assert librenderscope.friendly_vendor_charts(tmp_path) == {"zaakbrug": "WeAreFrank"}


def test_dimpact_alias_classified_as_dimpact(vp: ModuleType, librenderscope: ModuleType, tmp_path: Path):
    write_chart_yaml(
        tmp_path,
        [
            {"name": "brp-personen-mock", "alias": "brppersonenmock", "version": "1.0.0", "repository": "@dimpact"},
        ],
    )
    assert librenderscope.friendly_vendor_charts(tmp_path) == {"brppersonenmock": "Dimpact"}


def test_kiss_chart_overridden_to_icatt_despite_unmatching_repository(
    vp: ModuleType, librenderscope: ModuleType, tmp_path: Path
):
    """kiss-chart's repository has no vendor keyword: ICATT is a hardcoded
    override."""
    write_chart_yaml(
        tmp_path,
        [
            {
                "name": "kiss-chart",
                "alias": "kiss",
                "version": "1.0.0",
                "repository": "oci://ghcr.io/klantinteractie-servicesysteem",
            },
        ],
    )
    assert librenderscope.friendly_vendor_charts(tmp_path) == {"kiss": "ICATT"}


def test_local_file_dependency_classified_as_local(vp: ModuleType, librenderscope: ModuleType, tmp_path: Path):
    write_chart_yaml(
        tmp_path,
        [
            {"name": "mi-data", "alias": "mi", "version": "1.0.0", "repository": "file://../mi-data"},
        ],
    )
    assert librenderscope.friendly_vendor_charts(tmp_path) == {"mi": "Local"}


def test_unrelated_vendor_not_classified(vp: ModuleType, librenderscope: ModuleType, tmp_path: Path):
    write_chart_yaml(
        tmp_path,
        [
            {"name": "redis-operator", "version": "1.0.0", "repository": "@opstree"},
            {"name": "openbao", "version": "1.0.0", "repository": "https://openbao.github.io/openbao-helm"},
        ],
    )
    assert librenderscope.friendly_vendor_charts(tmp_path) == {}


def test_full_real_dependency_set_matches_expected_mapping(vp: ModuleType, librenderscope: ModuleType, tmp_path: Path):
    """Regression pin on known dependencies: catches keyword/override changes
    that break an existing classification."""
    write_chart_yaml(
        tmp_path,
        [
            {"name": "keycloak-operator", "version": "1.0.0", "repository": "@adfinis"},
            {"name": "clamav", "version": "1.0.0", "repository": "@wiremind"},
            {"name": "brp-personen-mock", "alias": "brppersonenmock", "version": "1.0.0", "repository": "@dimpact"},
            {"name": "mi-data", "alias": "mi", "version": "1.0.0", "repository": "file://../mi-data"},
            {"name": "openzaak", "version": "1.0.0", "repository": "@maykinmedia"},
            {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.0", "repository": "@zac"},
            {"name": "zaakbrug", "version": "1.0.0", "repository": "https://wearefrank.github.io/charts"},
            {"name": "zgw-office-addin", "version": "1.0.0", "repository": "@zgw-office-addin"},
            {
                "name": "internetaakafhandeling",
                "alias": "ita",
                "version": "1.0.0",
                "repository": "oci://ghcr.io/interne-taak-afhandeling",
            },
            {
                "name": "kiss-chart",
                "alias": "kiss",
                "version": "1.0.0",
                "repository": "oci://ghcr.io/klantinteractie-servicesysteem",
            },
            {"name": "pabc", "version": "1.0.0", "repository": "oci://ghcr.io/platform-autorisatie-beheer-component"},
            {"name": "notifynl-omc-nodep", "alias": "omc", "version": "1.0.0", "repository": "@worth-nl"},
            {"name": "redis-operator", "version": "1.0.0", "repository": "@opstree"},
            {"name": "eck-operator", "version": "1.0.0", "repository": "https://helm.elastic.co"},
            {"name": "openbao", "version": "1.0.0", "repository": "https://openbao.github.io/openbao-helm"},
        ],
    )
    assert librenderscope.friendly_vendor_charts(tmp_path) == {
        "brppersonenmock": "Dimpact",
        "mi": "Local",
        "openzaak": "Maykin",
        "zac": "Info(NL)",
        "zaakbrug": "WeAreFrank",
        "zgw-office-addin": "Info(NL)",
        "kiss": "ICATT",
        "omc": "Worth",
    }
    # deliberately NOT classified — not in vendor_classification.keywords/chart_overrides
    for unclassified in ("keycloak-operator", "clamav", "ita", "pabc", "redis-operator", "eck-operator", "openbao"):
        assert unclassified not in librenderscope.friendly_vendor_charts(tmp_path)
