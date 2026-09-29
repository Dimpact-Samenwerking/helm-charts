"""lib.chart -- path/version primitives, baselines and full_repository_for_path."""

from pathlib import Path
from types import ModuleType

import pytest

# --- get_path ---


def test_get_path_nested(libchartvaluestreeprimitives: ModuleType):
    assert libchartvaluestreeprimitives.get_path({"a": {"b": {"c": 1}}}, "a.b.c") == 1


def test_get_path_missing_returns_none(libchartvaluestreeprimitives: ModuleType):
    assert libchartvaluestreeprimitives.get_path({"a": {}}, "a.b.c") is None


def test_get_path_non_dict_intermediate_returns_none(libchartvaluestreeprimitives: ModuleType):
    assert libchartvaluestreeprimitives.get_path({"a": "scalar"}, "a.b") is None


# --- replace_scalar_value ---


def test_replace_scalar_value_preserves_quotes(libchartvaluestreeprimitives: ModuleType):
    assert (
        libchartvaluestreeprimitives.replace_scalar_value('      tag: "1.0.0@sha256:aaaa"\n', "2.0.0@sha256:bbbb")
        == '      tag: "2.0.0@sha256:bbbb"\n'
    )


def test_replace_scalar_value_preserves_bare_style(libchartvaluestreeprimitives: ModuleType):
    assert (
        libchartvaluestreeprimitives.replace_scalar_value("    version: 1.0.297\n", "1.0.298")
        == "    version: 1.0.298\n"
    )


def test_replace_scalar_value_preserves_trailing_comment(libchartvaluestreeprimitives: ModuleType):
    result = libchartvaluestreeprimitives.replace_scalar_value("    version: 1.0.297  # pinned\n", "1.0.298")
    assert result == "    version: 1.0.298  # pinned\n"


def test_replace_scalar_value_unparseable_line_raises(libchartvaluestreeprimitives: ModuleType):
    with pytest.raises(SystemExit):
        libchartvaluestreeprimitives.replace_scalar_value("not a key-value line at all\n", "x")


def test_replace_scalar_value_preserves_anchor_tag(libchartvaluestreeprimitives: ModuleType):
    """A YAML anchor definition keeps its "&anchor" after a bump; losing it breaks every "*anchor" alias."""
    assert (
        libchartvaluestreeprimitives.replace_scalar_value('        tag: &keycloakImageVersion "26.7.2"\n', "26.7.3")
        == '        tag: &keycloakImageVersion "26.7.3"\n'
    )
    assert (
        libchartvaluestreeprimitives.replace_scalar_value('        sha: &keycloakImageDigest "aaaa"\n', "dddd")
        == '        sha: &keycloakImageDigest "dddd"\n'
    )


# --- chart_version / SEMVER_RE ---


def test_chart_version_reads_top_level_version(libchartreleasebaselinebasics: ModuleType, tmp_path: Path):
    chart_yaml = tmp_path / "Chart.yaml"
    chart_yaml.write_text("apiVersion: v2\nname: podiumd\nversion: 4.9.0\n", encoding="utf-8")
    assert libchartreleasebaselinebasics.chart_version(chart_yaml) == "4.9.0"


def test_semver_re_matches_bare_version(libcharthistoricalbaselines: ModuleType):
    assert libcharthistoricalbaselines.SEMVER_RE.match("4.8.2")
    assert libcharthistoricalbaselines.SEMVER_RE.match("10.20.300")


def test_semver_re_rejects_anything_else(libcharthistoricalbaselines: ModuleType):
    assert not libcharthistoricalbaselines.SEMVER_RE.match("4.8")
    assert not libcharthistoricalbaselines.SEMVER_RE.match("v4.8.2")
    assert not libcharthistoricalbaselines.SEMVER_RE.match("--help")
    assert not libcharthistoricalbaselines.SEMVER_RE.match("4.8.2-rc1")


# --- upgrade_docs_baseline / release_table_baseline ---
# Two baselines: incremental (upgrade docs/images manifest) vs cumulative (release-table.csv).


def test_upgrade_docs_baseline_reads_the_key(libchartreleasebaselinebasics: ModuleType, tmp_path: Path):
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc" / "release-baseline.yaml").write_text(
        "upgrade_docs: '4.9.0'\nrelease_table: '4.8.5'\n", encoding="utf-8"
    )
    assert libchartreleasebaselinebasics.upgrade_docs_baseline(tmp_path) == "4.9.0"


def test_release_table_baseline_reads_the_key(libchartreleasebaselinebasics: ModuleType, tmp_path: Path):
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc" / "release-baseline.yaml").write_text(
        "upgrade_docs: '4.9.0'\nrelease_table: '4.8.5'\n", encoding="utf-8"
    )
    assert libchartreleasebaselinebasics.release_table_baseline(tmp_path) == "4.8.5"


def test_upgrade_docs_baseline_none_when_file_missing(libchartreleasebaselinebasics: ModuleType, tmp_path: Path):
    assert libchartreleasebaselinebasics.upgrade_docs_baseline(tmp_path) is None


def test_release_table_baseline_none_when_file_missing(libchartreleasebaselinebasics: ModuleType, tmp_path: Path):
    assert libchartreleasebaselinebasics.release_table_baseline(tmp_path) is None


def test_upgrade_docs_baseline_none_when_key_missing(libchartreleasebaselinebasics: ModuleType, tmp_path: Path):
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc" / "release-baseline.yaml").write_text("release_table: '4.8.5'\n", encoding="utf-8")
    assert libchartreleasebaselinebasics.upgrade_docs_baseline(tmp_path) is None


def test_release_table_baseline_none_when_key_missing(libchartreleasebaselinebasics: ModuleType, tmp_path: Path):
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc" / "release-baseline.yaml").write_text("upgrade_docs: '4.9.0'\n", encoding="utf-8")
    assert libchartreleasebaselinebasics.release_table_baseline(tmp_path) is None


# --- full_repository_for_path ---
# Host-qualified repository, not the stripped paths_by_repository key.


def test_full_repository_for_path_docker_hub_repository_gets_docker_io_host(
    tmp_path: Path, libchartrepoandpathresolution: ModuleType
):
    """Docker Hub repositories have no host in "repository:"."""
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    values = {"zac": {"image": {"repository": "curlimages/curl", "tag": "8.22.0@sha256:aaaa"}}}
    assert (
        libchartrepoandpathresolution.full_repository_for_path(tmp_path, deps, values, ("zac", "image"))
        == "docker.io/curlimages/curl"
    )


def test_full_repository_for_path_already_host_qualified_is_unchanged(
    tmp_path: Path, libchartrepoandpathresolution: ModuleType
):
    deps = [{"name": "brp-personen-mock", "alias": "brppersonenmock", "version": "1.2.9"}]
    values = {"brppersonenmock": {"image": {"repository": "ghcr.io/brp-api/personen-mock", "tag": "2.7.0@sha256:aaaa"}}}
    assert (
        libchartrepoandpathresolution.full_repository_for_path(tmp_path, deps, values, ("brppersonenmock", "image"))
        == "ghcr.io/brp-api/personen-mock"
    )


def test_full_repository_for_path_separate_registry_key_is_authoritative(
    tmp_path: Path, libchartrepoandpathresolution: ModuleType
):
    """A sibling "registry:" host (ACR, e.g. mi's azure-cli) is used as-is, not Docker Hub inference."""
    deps = [{"name": "mi-data", "alias": "mi", "version": "1.1.0"}]
    values = {
        "mi": {"image": {"registry": "mcr.microsoft.com", "repository": "azure-cli", "tag": "2.90.0@sha256:aaaa"}}
    }
    assert (
        libchartrepoandpathresolution.full_repository_for_path(tmp_path, deps, values, ("mi", "image"))
        == "mcr.microsoft.com/azure-cli"
    )


def test_full_repository_for_path_bare_namespace_registry_key_gets_docker_io_host(
    tmp_path: Path, libchartrepoandpathresolution: ModuleType
):
    """A bare Docker Hub namespace in "registry:" (zaakbrug's "wearefrank") gets the docker.io host."""
    deps = [{"name": "zaakbrug", "version": "2.3.32"}]
    values = {"zaakbrug": {"image": {"registry": "wearefrank", "repository": "zaakbrug", "tag": "1.26.18@sha256:aaaa"}}}
    assert (
        libchartrepoandpathresolution.full_repository_for_path(tmp_path, deps, values, ("zaakbrug", "image"))
        == "docker.io/wearefrank/zaakbrug"
    )


def test_full_repository_for_path_none_when_unresolvable(tmp_path: Path, libchartrepoandpathresolution: ModuleType):
    assert (
        libchartrepoandpathresolution.full_repository_for_path(tmp_path, [], {}, ("brppersonenmock", "image")) is None
    )
