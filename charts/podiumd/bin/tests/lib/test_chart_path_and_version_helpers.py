"""lib.chart — path/version primitives: get_path, replace_scalar_value,
chart_version, SEMVER_RE, upgrade_docs_baseline, release_table_baseline,
full_repository_for_path. Split out of the former test_chart.py (see
test_chart_historical_baselines_and_release.py, test_chart_dependency_and_
pull.py, test_chart_verify_digest_pin_and_subchart_basics.py, test_chart_
resolve_values_repos_and_paths.py, and test_chart_sidecar_rows_and_
wrappers.py for the rest)."""

import pytest

# --- get_path ---


def test_get_path_nested(libchartvaluestreeprimitives):
    assert libchartvaluestreeprimitives.get_path({"a": {"b": {"c": 1}}}, "a.b.c") == 1


def test_get_path_missing_returns_none(libchartvaluestreeprimitives):
    assert libchartvaluestreeprimitives.get_path({"a": {}}, "a.b.c") is None


def test_get_path_non_dict_intermediate_returns_none(libchartvaluestreeprimitives):
    assert libchartvaluestreeprimitives.get_path({"a": "scalar"}, "a.b") is None


# --- replace_scalar_value ---
# moved here from update-component-version (see
# tests/update-component-version/test_update_component_version.py for the
# ucv.replace_scalar_value re-export, still exercised via that import).


def test_replace_scalar_value_preserves_quotes(libchartvaluestreeprimitives):
    assert (
        libchartvaluestreeprimitives.replace_scalar_value('      tag: "1.0.0@sha256:aaaa"\n', "2.0.0@sha256:bbbb")
        == '      tag: "2.0.0@sha256:bbbb"\n'
    )


def test_replace_scalar_value_preserves_bare_style(libchartvaluestreeprimitives):
    assert (
        libchartvaluestreeprimitives.replace_scalar_value("    version: 1.0.297\n", "1.0.298")
        == "    version: 1.0.298\n"
    )


def test_replace_scalar_value_preserves_trailing_comment(libchartvaluestreeprimitives):
    result = libchartvaluestreeprimitives.replace_scalar_value("    version: 1.0.297  # pinned\n", "1.0.298")
    assert result == "    version: 1.0.298  # pinned\n"


def test_replace_scalar_value_unparseable_line_raises(libchartvaluestreeprimitives):
    with pytest.raises(SystemExit):
        libchartvaluestreeprimitives.replace_scalar_value("not a key-value line at all\n", "x")


def test_replace_scalar_value_preserves_anchor_tag(libchartvaluestreeprimitives):
    """Regression test: a line DEFINING a YAML anchor (e.g. keycloak-
    operator.operator.config.keycloakImage's own "tag:"/"sha:" fields,
    aliased elsewhere by keycloak.image via "*anchor") must keep its own
    "&anchor" marker after a value bump — dropping it would silently
    sever every "*anchor" reference elsewhere in the same file, turning
    each into a YAML parse error (an alias to an undefined anchor) on
    the very next load. Confirmed empirically to fail without this fix:
    the anchor tag was dropped entirely, producing a bare "tag: 26.7.3"
    line."""
    assert (
        libchartvaluestreeprimitives.replace_scalar_value('        tag: &keycloakImageVersion "26.7.2"\n', "26.7.3")
        == '        tag: &keycloakImageVersion "26.7.3"\n'
    )
    assert (
        libchartvaluestreeprimitives.replace_scalar_value('        sha: &keycloakImageDigest "aaaa"\n', "dddd")
        == '        sha: &keycloakImageDigest "dddd"\n'
    )


# --- chart_version / SEMVER_RE ---
# shared by create-doc-version, fix-doc-consistency, update-component-
# version, and create-podiumd-version's own current_chart_version()/
# *_VERSION_RE re-exports — see those scripts' own tests for the
# re-export coverage.


def test_chart_version_reads_top_level_version(libchartreleasebaselinebasics, tmp_path):
    chart_yaml = tmp_path / "Chart.yaml"
    chart_yaml.write_text("apiVersion: v2\nname: podiumd\nversion: 4.9.0\n", encoding="utf-8")
    assert libchartreleasebaselinebasics.chart_version(chart_yaml) == "4.9.0"


def test_semver_re_matches_bare_version(libcharthistoricalbaselines):
    assert libcharthistoricalbaselines.SEMVER_RE.match("4.8.2")
    assert libcharthistoricalbaselines.SEMVER_RE.match("10.20.300")


def test_semver_re_rejects_anything_else(libcharthistoricalbaselines):
    assert not libcharthistoricalbaselines.SEMVER_RE.match("4.8")
    assert not libcharthistoricalbaselines.SEMVER_RE.match("v4.8.2")
    assert not libcharthistoricalbaselines.SEMVER_RE.match("--help")
    assert not libcharthistoricalbaselines.SEMVER_RE.match("4.8.2-rc1")


# --- upgrade_docs_baseline / release_table_baseline ---
# release-baseline.yaml — see lib.chart's RELEASE_BASELINES_FILE_NAME/
# _release_baselines for why podiumd needs two baselines (incremental
# _UPGRADE_PATHS/images-manifest vs. cumulative release-table.csv).


def test_upgrade_docs_baseline_reads_the_key(libchartreleasebaselinebasics, tmp_path):
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc" / "release-baseline.yaml").write_text(
        "upgrade_docs: '4.9.0'\nrelease_table: '4.8.5'\n", encoding="utf-8"
    )
    assert libchartreleasebaselinebasics.upgrade_docs_baseline(tmp_path) == "4.9.0"


def test_release_table_baseline_reads_the_key(libchartreleasebaselinebasics, tmp_path):
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc" / "release-baseline.yaml").write_text(
        "upgrade_docs: '4.9.0'\nrelease_table: '4.8.5'\n", encoding="utf-8"
    )
    assert libchartreleasebaselinebasics.release_table_baseline(tmp_path) == "4.8.5"


def test_upgrade_docs_baseline_none_when_file_missing(libchartreleasebaselinebasics, tmp_path):
    assert libchartreleasebaselinebasics.upgrade_docs_baseline(tmp_path) is None


def test_release_table_baseline_none_when_file_missing(libchartreleasebaselinebasics, tmp_path):
    assert libchartreleasebaselinebasics.release_table_baseline(tmp_path) is None


def test_upgrade_docs_baseline_none_when_key_missing(libchartreleasebaselinebasics, tmp_path):
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc" / "release-baseline.yaml").write_text("release_table: '4.8.5'\n", encoding="utf-8")
    assert libchartreleasebaselinebasics.upgrade_docs_baseline(tmp_path) is None


def test_release_table_baseline_none_when_key_missing(libchartreleasebaselinebasics, tmp_path):
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc" / "release-baseline.yaml").write_text("upgrade_docs: '4.9.0'\n", encoding="utf-8")
    assert libchartreleasebaselinebasics.release_table_baseline(tmp_path) is None


# --- full_repository_for_path ---
# the fully host-qualified repository a manifest entry's own "url:"
# field (or a real registry call) needs — never the STRIPPED form
# paths_by_repository's own repo-group keys use.


def test_full_repository_for_path_docker_hub_repository_gets_docker_io_host(tmp_path, libchartrepoandpathresolution):
    """Docker Hub's own convention: no registry host embedded in
    "repository:" at all."""
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    values = {"zac": {"image": {"repository": "curlimages/curl", "tag": "8.22.0@sha256:aaaa"}}}
    assert (
        libchartrepoandpathresolution.full_repository_for_path(tmp_path, deps, values, ("zac", "image"))
        == "docker.io/curlimages/curl"
    )


def test_full_repository_for_path_already_host_qualified_is_unchanged(tmp_path, libchartrepoandpathresolution):
    deps = [{"name": "brp-personen-mock", "alias": "brppersonenmock", "version": "1.2.9"}]
    values = {"brppersonenmock": {"image": {"repository": "ghcr.io/brp-api/personen-mock", "tag": "2.7.0@sha256:aaaa"}}}
    assert (
        libchartrepoandpathresolution.full_repository_for_path(tmp_path, deps, values, ("brppersonenmock", "image"))
        == "ghcr.io/brp-api/personen-mock"
    )


def test_full_repository_for_path_separate_registry_key_is_authoritative(tmp_path, libchartrepoandpathresolution):
    """Regression test (mi's own real "azure-cli" case): a sibling
    "registry:" key alongside a bare "repository:" (Azure Container
    Registry's own convention) is used directly — never parse_repo's
    own Docker Hub inference, which would wrongly assume "docker.io/
    azure-cli"."""
    deps = [{"name": "mi-data", "alias": "mi", "version": "1.1.0"}]
    values = {
        "mi": {"image": {"registry": "mcr.microsoft.com", "repository": "azure-cli", "tag": "2.90.0@sha256:aaaa"}}
    }
    assert (
        libchartrepoandpathresolution.full_repository_for_path(tmp_path, deps, values, ("mi", "image"))
        == "mcr.microsoft.com/azure-cli"
    )


def test_full_repository_for_path_bare_namespace_registry_key_gets_docker_io_host(
    tmp_path, libchartrepoandpathresolution
):
    """Regression test (zaakbrug's own real case): the vendored zaakbrug
    chart's own upstream default sets "image.registry: wearefrank"
    alongside "image.repository: zaakbrug" — but "wearefrank" is a bare
    Docker Hub NAMESPACE stored in the same field mi's own real ACR host
    (mcr.microsoft.com) lives in, not a real DNS host itself (no "." or
    ":", not "localhost" — the same test strip_registry_host/parse_repo
    already use for the identical question elsewhere). Must still
    resolve to a real, host-qualified "docker.io/wearefrank/zaakbrug" —
    not the bare, unqualified "wearefrank/zaakbrug" a naive "registry:
    sibling is always a real host" assumption would produce."""
    deps = [{"name": "zaakbrug", "version": "2.3.32"}]
    values = {"zaakbrug": {"image": {"registry": "wearefrank", "repository": "zaakbrug", "tag": "1.26.18@sha256:aaaa"}}}
    assert (
        libchartrepoandpathresolution.full_repository_for_path(tmp_path, deps, values, ("zaakbrug", "image"))
        == "docker.io/wearefrank/zaakbrug"
    )


def test_full_repository_for_path_none_when_unresolvable(tmp_path, libchartrepoandpathresolution):
    assert (
        libchartrepoandpathresolution.full_repository_for_path(tmp_path, [], {}, ("brppersonenmock", "image")) is None
    )
