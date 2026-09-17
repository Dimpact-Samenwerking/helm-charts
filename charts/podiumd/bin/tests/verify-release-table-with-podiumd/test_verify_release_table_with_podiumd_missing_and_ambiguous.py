"""compare() (the pure comparison core) for verify-release-table-with-podiumd:
is_primary_image, plus everything compare() reports as missing (from
release-table.csv, from Chart.yaml/values.yaml), orphan/ambiguous/unresolved
rows, "MULTIPLE" (global.images) rows, and multi-image components. compare()
takes plain in-memory deps/values/lines/rows, so these tests need neither a
real Chart.yaml nor network access.

Split out of test_verify_release_table_with_podiumd.py (pylint
too-many-lines) -- purely a test reorganization, no behavior change. See the
sibling test_verify_release_table_with_podiumd_*.py files for the rest of
that suite."""

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

# zac's own PRIMARY image (zac.image, matching lib.chart.
# DEFAULT_IMAGE_PATHS) plus a sidecar image nested elsewhere (zac.
# opentelemetry-collector.image) that is NEVER zac's primary image, no
# matter how deep or shallow the nesting -- see lib.chart.
# image_paths_for / COMPONENT_IMAGE_PATHS.
ZAC_WITH_SIDECAR_BLOCK = ZAC_BLOCK + (
    "  opentelemetry-collector:\n"
    "    image:\n"
    "      repository: otel/opentelemetry-collector-contrib\n"
    f'      tag: "0.158.0@sha256:{DIGEST}"\n'
)


# --- is_primary_image ---


def test_is_primary_image_default_path(vrt):
    """DEFAULT_IMAGE_PATHS (["image"]) covers the common single-image
    component -- zac's own "zaakafhandelcomponent" pin, at zac.image.tag."""
    lines = values_lines(ZAC_BLOCK)
    pins = vrt.basenames_under_scope_any_tag(lines, "zac")["zaakafhandelcomponent"]
    assert vrt.is_primary_image("zaakafhandelcomponent", lines, pins[0]) is True


def test_is_primary_image_false_for_sidecar(vrt):
    """A sidecar image nested elsewhere is never the component's primary
    one, no matter how deep or shallow the nesting."""
    lines = values_lines(ZAC_WITH_SIDECAR_BLOCK)
    pins = vrt.basenames_under_scope_any_tag(lines, "zac")["opentelemetry-collector-contrib"]
    assert vrt.is_primary_image("zaakafhandelcomponent", lines, pins[0]) is False


def test_is_primary_image_multi_image_component_override(vrt):
    """COMPONENT_IMAGE_PATHS overrides DEFAULT_IMAGE_PATHS for a multi-
    image component -- zgw-office-addin's own frontend+backend are BOTH
    primary, per lib.chart.COMPONENT_IMAGE_PATHS."""
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


def test_compare_reports_dependency_with_no_release_table_row(vrt):
    deps = [{"name": "openklant", "alias": "", "version": "1.11.0"}]
    findings, _ = vrt.compare([], deps, {}, [])
    assert any("Chart.yaml dependency 'openklant'" in m for m in findings["missing_from_release_table"])


def test_compare_dependency_missing_hint_names_resolvable_identifier(vrt):
    """The finding's own second line must tell a human exactly what text
    to write on the Confluence page so the NEXT export resolves this row
    back to the same dependency (see lib.export's component_and_alias) —
    the dependency's own alias when it has one (a real Chart.yaml
    dependency's alias always wins an exact-match tier on its own)."""
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    findings, _ = vrt.compare([], deps, {}, [])
    hint = next(m for m in findings["missing_from_release_table"] if "zaakafhandelcomponent" in m)
    assert "\n      Confluence: add row to whichever table fits" in hint
    assert 'Name or "Used by": "zac"' in hint


def test_compare_reports_image_pinned_but_not_tracked(vrt):
    """values.yaml pins an image under zac's own scope that no
    release-table.csv row mentions at all."""
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    rows = [csv_row("Zaak - ZAC", "zaakafhandelcomponent", alias="zac", image_basename="", target_helm="1.0.297")]
    findings, _ = vrt.compare(rows, deps, {}, values_lines(ZAC_BLOCK))
    assert any(
        "'zaakafhandelcomponent' is pinned in values.yaml but not tracked" in m
        for m in findings["missing_from_release_table"]
    )


def test_compare_missing_image_hint_names_table_and_resolvable_row_text(vrt):
    """The finding's own second line must name the exact Confluence table
    (read off this component's own existing row) and exactly what a new
    row needs to say — a Name containing the missing basename — so
    resolve_image_basenames/component_and_alias resolve it on the next
    export, not just a vague pointer to "add it somewhere". No "Used by"
    mentioned: "Product component versies" (like Common Ground/Overige)
    has no such column at all -- only "Technische component versies"
    does (see missing_image_hint). The version is explicitly labeled
    "App" since this table still splits its "Versie ..." column into
    separate App/Helm sub-columns — a human needs to know which one to
    fill in."""
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    rows = [csv_row("Zaak - ZAC", "zaakafhandelcomponent", alias="zac", image_basename="", target_helm="1.0.297")]
    findings, _ = vrt.compare(rows, deps, {}, values_lines(ZAC_BLOCK))
    hint = next(m for m in findings["missing_from_release_table"] if "zaakafhandelcomponent" in m)
    assert '\n      Confluence: add row to "Product component versies"' in hint
    assert 'Name containing "zaakafhandelcomponent"' in hint
    assert "Used by" not in hint
    assert "App version (currently) 5.4.3" in hint


def test_compare_missing_primary_image_uses_own_table_without_used_by(vrt):
    """A component's own PRIMARY application image (see lib.chart.
    image_paths_for/DEFAULT_IMAGE_PATHS -- zac.image, here) never needs
    "Used by", even when its only tracked row happens to live on
    "Technische component versies": it's this row's own identity, not a
    sibling image being attributed to some other consuming component."""
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    rows = [
        {
            **csv_row(
                "Elastic operator", "zaakafhandelcomponent", alias="zac", image_basename="", target_helm="1.0.297"
            ),
            "section": "Technische",
        }
    ]
    findings, _ = vrt.compare(rows, deps, {}, values_lines(ZAC_BLOCK))
    hint = next(m for m in findings["missing_from_release_table"] if "zaakafhandelcomponent" in m)
    assert '\n      Confluence: add row to "Technische component versies"' in hint
    assert 'Name containing "zaakafhandelcomponent"' in hint
    assert "Used by" not in hint


def test_compare_missing_sidecar_image_always_goes_to_technische_with_used_by(vrt):
    """A component's own sidecar/init-container image -- NOT its primary
    application image, see lib.chart.image_paths_for -- always goes to
    "Technische component versies" with "Used by" naming the component,
    regardless of which table the component's own primary row actually
    lives on (here, "Product")."""
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
    findings, _ = vrt.compare(rows, deps, {}, values_lines(ZAC_WITH_SIDECAR_BLOCK))
    hint = next(m for m in findings["missing_from_release_table"] if "opentelemetry-collector-contrib" in m)
    assert '\n      Confluence: add row to "Technische component versies"' in hint
    assert '"Used by": "zac", Name containing "opentelemetry-collector-contrib"' in hint


# --- compare(): missing from Chart.yaml / values.yaml ---


def test_compare_reports_row_component_no_longer_a_dependency(vrt):
    rows = [csv_row("Long Gone", "longgone")]
    findings, _ = vrt.compare(rows, [], {}, [])
    assert any(
        "resolves to component 'longgone', which is not a Chart.yaml dependency" in m
        for m in findings["missing_from_chart"]
    )


def test_compare_reports_tracked_image_no_longer_pinned(vrt):
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
    findings, _ = vrt.compare(rows, deps, {}, values_lines(ZAC_BLOCK))
    assert any(
        "release-table image 'opa' for component 'zaakafhandelcomponent'" in m for m in findings["missing_from_chart"]
    )


# --- compare(): orphan components (no separate Chart.yaml dependency) ---


def test_compare_checks_images_for_orphan_values_yaml_component(vrt):
    """frankgateway-style: no Chart.yaml dependency, but a real top-level
    values.yaml key — its own image(s) are still checked, just without a
    chart-version comparison (no Chart.yaml "version:" to compare against)."""
    frank_block = (
        f'frankgateway:\n  image:\n    repository: ghcr.io/wearefrank/frank-gateway\n    tag: "1.1.0@sha256:{DIGEST}"\n'
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
    f'global:\n  images:\n    curl:\n      repository: docker.io/curlimages/curl\n      tag: "8.22.0@sha256:{DIGEST}"\n'
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
    assert any(
        "'global' image 'curl' is pinned in values.yaml but not tracked" in m
        for m in findings["missing_from_release_table"]
    )


def test_compare_missing_multiple_image_hint_has_no_used_by_and_guesses_technische(vrt):
    """A MULTIPLE row resolves purely from its own Name relating to the
    global image key -- no "Used by" needed (see
    resolve_image_basenames). With zero existing "MULTIPLE" rows to read
    a section from at all, "Technische" is still a safe guess (every
    global.images entry is, by convention, exported there)."""
    findings, _ = vrt.compare([], [], {}, values_lines(GLOBAL_CURL_BLOCK))
    hint = next(m for m in findings["missing_from_release_table"] if "'global' image 'curl'" in m)
    assert '\n      Confluence: add row to "Technische component versies"' in hint
    assert 'Name containing "curl"' in hint
    assert "Used by" not in hint
    assert "App version (currently) 8.22.0" in hint


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
    rows = [
        csv_row(
            "Office Add-in",
            "zgw-office-addin",
            image_basename="zgw-office-addin-frontend,zgw-office-addin-backend",
            target_app="0.12.0",
            target_helm="0.0.92",
        )
    ]
    findings, _ = vrt.compare(rows, deps, {}, values_lines(block))
    assert len(findings["mismatches"]) == 2
    assert any("zgw-office-addin-frontend" in m for m in findings["mismatches"])
    assert any("zgw-office-addin-backend" in m for m in findings["mismatches"])
