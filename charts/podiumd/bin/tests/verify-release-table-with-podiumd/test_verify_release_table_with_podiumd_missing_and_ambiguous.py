"""compare(): is_primary_image, missing/orphan/ambiguous/unresolved rows,
MULTIPLE (global.images) rows and multi-image components. In-memory inputs;
no Chart.yaml or network."""

from types import ModuleType

import pytest

DIGEST = "a" * 64


def csv_row(name, component, alias="", image_basename="", source_app="", source_helm="", target_app="", target_helm=""):
    return {
        "section": "Product",
        "vendor": "",
        "used_by": "",
        "name": name,
        "component": component,
        "alias": alias,
        "image_basename": image_basename,
        "source_version_app": source_app,
        "source_version_helm": source_helm,
        "target_version_app": target_app,
        "target_version_helm": target_helm,
    }


def values_lines(*blocks):
    return "\n".join(blocks).splitlines()


ZAC_BLOCK = f'zac:\n  image:\n    repository: ghcr.io/infonl/zaakafhandelcomponent\n    tag: "5.4.3@sha256:{DIGEST}"\n'

# zac's primary image (zac.image) plus a nested sidecar that is never
# primary, however deep it is nested.
ZAC_WITH_SIDECAR_BLOCK = ZAC_BLOCK + (
    "  opentelemetry-collector:\n"
    "    image:\n"
    "      repository: otel/opentelemetry-collector-contrib\n"
    f'      tag: "0.158.0@sha256:{DIGEST}"\n'
)


# --- is_primary_image ---


def test_is_primary_image_default_path(vrt: ModuleType):
    """DEFAULT_IMAGE_PATHS (["image"]) covers the single-image component."""
    lines = values_lines(ZAC_BLOCK)
    pins = vrt.basenames_under_scope_any_tag(lines, "zac")["zaakafhandelcomponent"]
    assert vrt.is_primary_image("zaakafhandelcomponent", lines, pins[0]) is True


def test_is_primary_image_false_for_sidecar(vrt: ModuleType):
    """A nested sidecar image is never primary."""
    lines = values_lines(ZAC_WITH_SIDECAR_BLOCK)
    pins = vrt.basenames_under_scope_any_tag(lines, "zac")["opentelemetry-collector-contrib"]
    assert vrt.is_primary_image("zaakafhandelcomponent", lines, pins[0]) is False


def test_is_primary_image_multi_image_component_override(vrt: ModuleType):
    """COMPONENT_IMAGE_PATHS overrides the default: both zgw-office-addin
    images are primary."""
    lines = values_lines(
        "zgw-office-addin:\n"
        "  frontend:\n"
        "    image:\n"
        "      repository: ghcr.io/infonl/zgw-office-addin-frontend\n"
        f'      tag: "1.0.0@sha256:{DIGEST}"\n'
        "  backend:\n"
        "    image:\n"
        "      repository: ghcr.io/infonl/zgw-office-addin-backend\n"
        f'      tag: "1.0.0@sha256:{DIGEST}"\n'
    )
    available = vrt.basenames_under_scope_any_tag(lines, "zgw-office-addin")
    frontend_pin = available["zgw-office-addin-frontend"][0]
    backend_pin = available["zgw-office-addin-backend"][0]
    assert vrt.is_primary_image("zgw-office-addin", lines, frontend_pin) is True
    assert vrt.is_primary_image("zgw-office-addin", lines, backend_pin) is True


# --- compare(): missing from release-table.csv ---


def test_compare_reports_dependency_with_no_release_table_row(vrt: ModuleType):
    deps = [{"name": "openklant", "alias": "", "version": "1.11.0"}]
    findings, _ = vrt.compare([], vrt.ChartState(None, deps, {}, []))
    assert any("Chart.yaml dependency 'openklant'" in m for m in findings["missing_from_release_table"])


def test_compare_dependency_missing_hint_names_resolvable_identifier(vrt: ModuleType):
    """The hint names the text to put on Confluence so the next export
    resolves the row back to this dependency: its alias when it has one."""
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    findings, _ = vrt.compare([], vrt.ChartState(None, deps, {}, []))
    hint = next(m for m in findings["missing_from_release_table"] if "zaakafhandelcomponent" in m)
    assert "\n      Confluence: add row to whichever table fits" in hint
    assert 'Name or "Used by": "zac"' in hint


def test_compare_reports_image_pinned_but_not_tracked(vrt: ModuleType):
    """An image pinned under zac's scope that no CSV row mentions."""
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    rows = [csv_row("Zaak - ZAC", "zaakafhandelcomponent", alias="zac", image_basename="", target_helm="1.0.297")]
    findings, _ = vrt.compare(rows, vrt.ChartState(None, deps, {}, values_lines(ZAC_BLOCK)))
    assert any(
        "'zaakafhandelcomponent' is pinned in values.yaml but not tracked" in m
        for m in findings["missing_from_release_table"]
    )


def test_compare_missing_image_hint_names_table_and_resolvable_row_text(vrt: ModuleType):
    """The hint names the exact table (from the component's existing row)
    and the Name with bracketed identifier. No "Used by": Product tables
    lack that column. "App" is explicit because this table splits App/Helm."""
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    rows = [csv_row("Zaak - ZAC", "zaakafhandelcomponent", alias="zac", image_basename="", target_helm="1.0.297")]
    findings, _ = vrt.compare(rows, vrt.ChartState(None, deps, {}, values_lines(ZAC_BLOCK)))
    hint = next(m for m in findings["missing_from_release_table"] if "zaakafhandelcomponent" in m)
    assert '\n      Confluence: add row to "Product component versies"' in hint
    assert 'Name "<name> (zac)"' in hint
    assert "Used by" not in hint
    assert "App version (currently) 5.4.3" in hint


def test_compare_missing_primary_image_uses_own_table_without_used_by(vrt: ModuleType):
    """A component's primary image never needs "Used by", even on a
    Technische table: it's the row's own identity."""
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    rows = [
        {
            **csv_row(
                "Elastic operator", "zaakafhandelcomponent", alias="zac", image_basename="", target_helm="1.0.297"
            ),
            "section": "Technische",
        }
    ]
    findings, _ = vrt.compare(rows, vrt.ChartState(None, deps, {}, values_lines(ZAC_BLOCK)))
    hint = next(m for m in findings["missing_from_release_table"] if "zaakafhandelcomponent" in m)
    assert '\n      Confluence: add row to "Technische component versies"' in hint
    assert 'Name "<name> (zac)"' in hint
    assert "Used by" not in hint


def test_compare_missing_sidecar_image_always_goes_to_technische_with_used_by(vrt: ModuleType):
    """A sidecar image always goes to Technische with "Used by" naming the
    component, wherever its primary row lives."""
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    rows = [
        csv_row(
            "Zaak - ZAC",
            "zaakafhandelcomponent",
            alias="zac",
            image_basename="zaakafhandelcomponent",
            target_helm="1.0.297",
        )
    ]
    findings, _ = vrt.compare(rows, vrt.ChartState(None, deps, {}, values_lines(ZAC_WITH_SIDECAR_BLOCK)))
    hint = next(m for m in findings["missing_from_release_table"] if "opentelemetry-collector-contrib" in m)
    assert '\n      Confluence: add row to "Technische component versies"' in hint
    assert '"Used by": "zac", Name "<name> (opentelemetry-collector-contrib)"' in hint


# --- compare(): missing from Chart.yaml / values.yaml ---


def test_compare_reports_row_component_no_longer_a_dependency(vrt: ModuleType):
    rows = [csv_row("Long Gone", "longgone")]
    findings, _ = vrt.compare(rows, vrt.ChartState(None, [], {}, []))
    assert any(
        "resolves to component 'longgone', which is not a Chart.yaml dependency" in m
        for m in findings["missing_from_chart"]
    )


def test_compare_reports_tracked_image_no_longer_pinned(vrt: ModuleType):
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    rows = [
        csv_row(
            "Zaak - ZAC",
            "zaakafhandelcomponent",
            alias="zac",
            image_basename="zaakafhandelcomponent",
            target_helm="1.0.297",
        ),
        csv_row(
            "Zaak - ZAC OPA",
            "zaakafhandelcomponent",
            alias="zac",
            image_basename="opa",
            target_app="1.17.1",
            target_helm="1.0.297",
        ),
    ]
    findings, _ = vrt.compare(rows, vrt.ChartState(None, deps, {}, values_lines(ZAC_BLOCK)))
    assert any(
        "release-table image 'opa' for component 'zaakafhandelcomponent'" in m for m in findings["missing_from_chart"]
    )


# --- compare(): orphan components (no separate Chart.yaml dependency) ---


def test_compare_checks_images_for_orphan_values_yaml_component(vrt: ModuleType):
    """No Chart.yaml dependency but a top-level values.yaml key: images are
    still checked, without a chart-version comparison."""
    frank_block = (
        f'frankgateway:\n  image:\n    repository: ghcr.io/wearefrank/frank-gateway\n    tag: "1.1.0@sha256:{DIGEST}"\n'
    )
    rows = [csv_row("Frank Gateway", "frankgateway", image_basename="frank-gateway", target_app="1.1.1")]
    findings, unresolved = vrt.compare(rows, vrt.ChartState(None, [], {"frankgateway": {}}, values_lines(frank_block)))
    assert any("target 1.1.1 != values.yaml 1.1.0" in m for m in findings["mismatches"])
    assert "missing_from_chart" not in findings
    assert unresolved == []


def test_compare_orphan_component_absent_from_values_yaml_is_missing_from_chart(vrt: ModuleType):
    rows = [csv_row("Frank Gateway", "frankgateway")]
    findings, _ = vrt.compare(rows, vrt.ChartState(None, [], {}, []))
    assert any("component 'frankgateway'" in m for m in findings["missing_from_chart"])


# --- compare(): ambiguous pins ---


def test_compare_reports_ambiguous_when_basename_pinned_at_multiple_versions(vrt: ModuleType):
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
    findings, _ = vrt.compare(rows, vrt.ChartState(None, deps, {}, values_lines(block)))
    assert any("pinned at 2 different versions" in m for m in findings["ambiguous"])
    assert "mismatches" not in findings


def test_compare_reports_ambiguous_when_unscoped_basename_matches_different_repos(vrt: ModuleType):
    """A basename only under two sibling scopes with different repositories
    (the "redis" collision) is not trusted, even if versions agree."""
    block = (
        "zac:\n"
        "  image:\n"
        f'    repository: ghcr.io/infonl/zaakafhandelcomponent\n    tag: "5.4.3@sha256:{DIGEST}"\n'
        "redis-operator:\n"
        "  image:\n"
        f'    repository: quay.io/opstree/redis\n    tag: "7.2.0@sha256:{DIGEST}"\n'
        "global:\n"
        "  images:\n"
        "    redis:\n"
        f'      repository: docker.io/library/redis\n      tag: "7.2.0@sha256:{DIGEST}"\n'
    )
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    rows = [csv_row("Zaak - ZAC", "zaakafhandelcomponent", alias="zac", image_basename="redis", target_app="7.2.0")]
    findings, _ = vrt.compare(rows, vrt.ChartState(None, deps, {}, values_lines(block)))
    assert any("matches 2 different repositories" in m for m in findings["ambiguous"])
    assert "mismatches" not in findings


def test_compare_unscoped_basename_in_one_repository_is_still_compared(vrt: ModuleType):
    """The collision guard only fires across repositories: a single
    sibling-scope match is still compared against the row's target."""
    block = (
        "zac:\n"
        "  image:\n"
        f'    repository: ghcr.io/infonl/zaakafhandelcomponent\n    tag: "5.4.3@sha256:{DIGEST}"\n'
        "redis-operator:\n"
        "  image:\n"
        f'    repository: quay.io/opstree/redis\n    tag: "7.2.0@sha256:{DIGEST}"\n'
    )
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    rows = [csv_row("Zaak - ZAC", "zaakafhandelcomponent", alias="zac", image_basename="redis", target_app="7.3.0")]
    findings, _ = vrt.compare(rows, vrt.ChartState(None, deps, {}, values_lines(block)))
    assert "ambiguous" not in findings
    assert any("7.3.0" in m and "7.2.0" in m for m in findings["mismatches"])


# --- compare(): unresolved components ---


@pytest.mark.parametrize("component", ["", "UNKNOWN"])
def test_compare_lists_unresolved_rows_separately(vrt: ModuleType, component):
    rows = [csv_row("Solr", component)]
    findings, unresolved = vrt.compare(rows, vrt.ChartState(None, [], {}, []))
    assert findings == {}
    assert unresolved == rows


# --- compare(): MULTIPLE (global.images) rows ---

GLOBAL_CURL_BLOCK = (
    f'global:\n  images:\n    curl:\n      repository: docker.io/curlimages/curl\n      tag: "8.22.0@sha256:{DIGEST}"\n'
)


def test_compare_checks_multiple_row_against_global_images(vrt: ModuleType):
    """A MULTIPLE row (shared base image in global.images) is checked against
    the "global" scope, not skipped as unresolved."""
    rows = [csv_row("Curl", "MULTIPLE", alias="MULTIPLE", image_basename="curl", target_app="8.23.0")]
    findings, unresolved = vrt.compare(rows, vrt.ChartState(None, [], {}, values_lines(GLOBAL_CURL_BLOCK)))
    assert any("target 8.23.0 != values.yaml 8.22.0" in m for m in findings["mismatches"])
    assert unresolved == []


def test_compare_multiple_row_matching_global_image_passes(vrt: ModuleType):
    rows = [csv_row("Curl", "MULTIPLE", alias="MULTIPLE", image_basename="curl", target_app="8.22.0")]
    findings, unresolved = vrt.compare(rows, vrt.ChartState(None, [], {}, values_lines(GLOBAL_CURL_BLOCK)))
    assert findings == {}
    assert unresolved == []


def test_compare_multiple_row_with_no_image_basename_is_silently_skipped(vrt: ModuleType):
    """A MULTIPLE row without image_basename has nothing to check: not an error."""
    rows = [csv_row("Something Ambiguous", "MULTIPLE", alias="MULTIPLE", image_basename="")]
    findings, unresolved = vrt.compare(rows, vrt.ChartState(None, [], {}, []))
    assert findings == {}
    assert unresolved == []


def test_compare_reports_global_image_with_no_release_table_row(vrt: ModuleType):
    findings, _ = vrt.compare([], vrt.ChartState(None, [], {}, values_lines(GLOBAL_CURL_BLOCK)))
    assert any(
        "'global' image 'curl' is pinned in values.yaml but not tracked" in m
        for m in findings["missing_from_release_table"]
    )


def test_compare_missing_multiple_image_hint_has_no_used_by_and_guesses_technische(vrt: ModuleType):
    """A MULTIPLE row needs no "Used by"; with no existing MULTIPLE row to copy
    the section from, "Technische" is the safe guess (global.images convention)."""
    findings, _ = vrt.compare([], vrt.ChartState(None, [], {}, values_lines(GLOBAL_CURL_BLOCK)))
    hint = next(m for m in findings["missing_from_release_table"] if "'global' image 'curl'" in m)
    assert '\n      Confluence: add row to "Technische component versies"' in hint
    assert 'Name "<name> (curl)"' in hint
    assert "Used by" not in hint
    assert "App version (currently) 8.22.0" in hint


# --- multi-image component (e.g. zgw-office-addin) ---


def test_compare_multi_image_component_checks_every_basename(vrt: ModuleType):
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
    rows = [
        csv_row(
            "Office Add-in",
            "zgw-office-addin",
            image_basename="zgw-office-addin-frontend,zgw-office-addin-backend",
            target_app="0.12.0",
            target_helm="0.0.92",
        )
    ]
    findings, _ = vrt.compare(rows, vrt.ChartState(None, deps, {}, values_lines(block)))
    assert len(findings["mismatches"]) == 2
    assert any("zgw-office-addin-frontend" in m for m in findings["mismatches"])
    assert any("zgw-office-addin-backend" in m for m in findings["mismatches"])
