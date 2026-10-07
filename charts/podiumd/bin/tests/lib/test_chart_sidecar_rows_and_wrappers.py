"""lib.chart: sidecar row naming, subchart template/default-repository lookup, registry wrappers."""

import io
import tarfile

from pathlib import Path
from types import ModuleType

import pytest
import yaml


def make_tgz(charts_dir, name, version, values, templates=None, chart_yaml=None, raw_files=None):
    """Write a minimal vendored <name>-<version>.tgz.

    `templates` ({filename: text}) go under <name>/templates/, `chart_yaml`
    becomes <name>/Chart.yaml, and `raw_files` ({tar path: text}) are written
    verbatim, for content yaml.safe_dump can't produce (commented-out lines).
    """
    charts_dir.mkdir(parents=True, exist_ok=True)
    tgz_path = charts_dir / f"{name}-{version}.tgz"
    data = yaml.safe_dump(values).encode("utf-8")
    with tarfile.open(tgz_path, "w:gz") as tar:
        info = tarfile.TarInfo(name=f"{name}/values.yaml")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
        for filename, text in (templates or {}).items():
            tpl_data = text.encode("utf-8")
            tpl_info = tarfile.TarInfo(name=f"{name}/templates/{filename}")
            tpl_info.size = len(tpl_data)
            tar.addfile(tpl_info, io.BytesIO(tpl_data))
        if chart_yaml is not None:
            chart_data = yaml.safe_dump(chart_yaml).encode("utf-8")
            chart_info = tarfile.TarInfo(name=f"{name}/Chart.yaml")
            chart_info.size = len(chart_data)
            tar.addfile(chart_info, io.BytesIO(chart_data))
        for internal_path, text in (raw_files or {}).items():
            raw_data = text.encode("utf-8")
            raw_info = tarfile.TarInfo(name=internal_path)
            raw_info.size = len(raw_data)
            tar.addfile(raw_info, io.BytesIO(raw_data))
    return tgz_path


# --- canonical_sidecar_row_names ---


def test_canonical_sidecar_row_names_dependency_sidecar(tmp_path: Path, libchartrepoandpathresolution: ModuleType):
    dep = {"name": "redis-operator", "alias": "", "version": "0.26.0"}
    values = {"redis-operator": {"redis-ha": {"image": {"repository": "quay.io/opstree/redis"}}}}
    paths = [("redis-operator", "redis-ha", "image")]

    names = libchartrepoandpathresolution.canonical_sidecar_row_names(tmp_path, [dep], values, paths)

    assert names == {"redis-operator - redis": ("redis-operator", "redis-ha", "image")}


def test_canonical_sidecar_row_names_native_component_sidecar(
    tmp_path: Path, libchartrepoandpathresolution: ModuleType
):
    """A native component (no Chart.yaml dependency, deps empty) still owns its sidecars."""
    values = {"frankgateway": {"etcd": {"image": {"repository": "quay.io/coreos/etcd"}}}}
    paths = [("frankgateway", "etcd", "image")]

    names = libchartrepoandpathresolution.canonical_sidecar_row_names(tmp_path, [], values, paths)

    assert names == {"frankgateway - etcd": ("frankgateway", "etcd", "image")}


def test_canonical_sidecar_row_names_excludes_native_components_own_primary_image(
    tmp_path: Path, libchartrepoandpathresolution: ModuleType
):
    """A native component's own primary image is not a sidecar."""
    values = {"frankgateway": {"image": {"repository": "ghcr.io/wearefrank/frank-gateway"}}}
    paths = [("frankgateway", "image")]

    names = libchartrepoandpathresolution.canonical_sidecar_row_names(tmp_path, [], values, paths)

    assert names == {}


def test_canonical_sidecar_row_names_excludes_dependencys_own_primary_image(
    tmp_path: Path, libchartrepoandpathresolution: ModuleType
):
    """A dependency's primary image is not a sidecar; match_dependency already covers it."""
    dep = {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}
    values = {"zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent"}}}
    paths = [("zac", "image")]

    names = libchartrepoandpathresolution.canonical_sidecar_row_names(tmp_path, [dep], values, paths)

    assert names == {}


def test_canonical_sidecar_row_names_self_referential_basename_falls_back_to_path_segment(
    tmp_path: Path, libchartrepoandpathresolution: ModuleType
):
    """A sidecar whose basename equals its values key uses the parent path segment instead.

    Avoids a confusing "<key> - <key>" name.
    """
    dep = {"name": "redis-operator", "alias": "", "version": "0.26.1"}
    values = {"redis-operator": {"redisOperator": {"image": {"repository": "quay.io/opstree/redis-operator"}}}}
    paths = [("redis-operator", "redisOperator", "image")]

    names = libchartrepoandpathresolution.canonical_sidecar_row_names(tmp_path, [dep], values, paths)

    assert names == {"redis-operator - redisOperator": ("redis-operator", "redisOperator", "image")}


def test_canonical_sidecar_row_names_excludes_sidecar_aliasing_an_owners_primary(
    tmp_path: Path, libchartrepoandpathresolution: ModuleType
):
    """A sidecar aliasing another owner's primary image (keycloak) gets no row of its own."""
    dep = {"name": "keycloak-operator", "alias": "", "version": "1.13.0"}
    values = {
        "keycloak": {"image": {"repository": "quay.io/keycloak/keycloak"}},
        "keycloak-operator": {
            "operator": {
                "image": {"repository": "quay.io/keycloak/keycloak-operator"},
                "config": {"keycloakImage": {"repository": "quay.io/keycloak/keycloak"}},
            }
        },
    }
    paths = [
        ("keycloak", "image"),
        ("keycloak-operator", "operator", "image"),
        ("keycloak-operator", "operator", "config", "keycloakImage"),
    ]

    names = libchartrepoandpathresolution.canonical_sidecar_row_names(tmp_path, [dep], values, paths)

    assert names == {}


def test_canonical_sidecar_row_names_self_referential_basename_no_fallback_segment_is_excluded(
    tmp_path: Path, libchartrepoandpathresolution: ModuleType
):
    """A self-referential path with no middle segment to fall back to is excluded."""
    dep = {"name": "keycloak-operator", "alias": "", "version": "1.12.1"}
    values = {"keycloak-operator": {"image": {"repository": "quay.io/keycloak/keycloak-operator"}}}
    paths = [("keycloak-operator", "image")]

    names = libchartrepoandpathresolution.canonical_sidecar_row_names(tmp_path, [dep], values, paths)

    assert names == {}


def test_canonical_sidecar_row_names_global_shared_image(tmp_path: Path, libchartrepoandpathresolution: ModuleType):
    """A "global" image is named by its bare basename (update-image-version's MULTIPLE_KEY)."""
    values = {"global": {"images": {"nginx": {"image": {"repository": "docker.io/nginxinc/nginx-unprivileged"}}}}}
    paths = [("global", "images", "nginx", "image")]

    names = libchartrepoandpathresolution.canonical_sidecar_row_names(tmp_path, [], values, paths)

    assert names == {"nginx-unprivileged": ("global", "images", "nginx", "image")}


def test_canonical_sidecar_row_names_excludes_sidecar_sharing_a_global_repository(
    tmp_path: Path, libchartrepoandpathresolution: ModuleType
):
    """Sidecars aliasing a global anchor get no per-component names, only the global one.

    Otherwise one version bump shows up as several -upgrade.md rows.
    """
    deps = [
        {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"},
        {"name": "frankgateway", "alias": "", "version": "1.1.0"},
    ]
    values = {
        "global": {"images": {"nginx": {"repository": "nginxinc/nginx-unprivileged"}}},
        "zac": {"nginx": {"image": {"repository": "nginxinc/nginx-unprivileged"}}},
        "frankgateway": {"dashboard": {"auth": {"shim": {"image": {"repository": "nginxinc/nginx-unprivileged"}}}}},
    }
    paths = [
        ("global", "images", "nginx"),
        ("zac", "nginx", "image"),
        ("frankgateway", "dashboard", "auth", "shim", "image"),
    ]

    names = libchartrepoandpathresolution.canonical_sidecar_row_names(tmp_path, deps, values, paths)

    assert names == {"nginx-unprivileged": ("global", "images", "nginx")}


def test_canonical_sidecar_row_names_multiple_sidecars_stay_distinct(
    tmp_path: Path, libchartrepoandpathresolution: ModuleType
):
    values = {
        "redis-operator": {
            "redis-ha": {"image": {"repository": "quay.io/opstree/redis"}},
            "redis-exporter": {"image": {"repository": "quay.io/opstree/redis-exporter"}},
        }
    }
    dep = {"name": "redis-operator", "alias": "", "version": "0.26.0"}
    paths = [("redis-operator", "redis-ha", "image"), ("redis-operator", "redis-exporter", "image")]

    names = libchartrepoandpathresolution.canonical_sidecar_row_names(tmp_path, [dep], values, paths)

    assert names == {
        "redis-operator - redis": ("redis-operator", "redis-ha", "image"),
        "redis-operator - redis-exporter": ("redis-operator", "redis-exporter", "image"),
    }


# --- subchart_template_text ---


def test_subchart_template_text_concatenates_all_template_files(
    tmp_path: Path, libchartrepoandpathresolution: ModuleType
):
    make_tgz(
        tmp_path / "charts",
        "pabc",
        "1.1.1",
        {"image": {"repository": "pabc/pabc-api"}},
        templates={
            "deployment.yaml": "image: {{ .Values.image.repository }}\n",
            "service.yaml": "kind: Service\n",
        },
    )
    dep = {"name": "pabc", "version": "1.1.1"}
    text = libchartrepoandpathresolution.subchart_template_text(tmp_path, dep)
    assert "{{ .Values.image.repository }}" in text
    assert "kind: Service" in text


def test_subchart_template_text_missing_tgz_returns_none(tmp_path: Path, libchartrepoandpathresolution: ModuleType):
    dep = {"name": "pabc", "version": "1.1.1"}
    assert libchartrepoandpathresolution.subchart_template_text(tmp_path, dep) is None


def test_subchart_template_text_no_templates_dir_returns_none(
    tmp_path: Path, libchartrepoandpathresolution: ModuleType
):
    """No templates/ returns None ("can't tell"), not "", so callers can tell the cases apart."""
    make_tgz(tmp_path / "charts", "pabc", "1.1.1", {"image": {"repository": "pabc/pabc-api"}})
    dep = {"name": "pabc", "version": "1.1.1"}
    assert libchartrepoandpathresolution.subchart_template_text(tmp_path, dep) is None


# --- subchart_default_repository ---


def test_subchart_default_repository_resolves_via_alias(tmp_path: Path, libchartrepoandpathresolution: ModuleType):
    """The .tgz is keyed by the real chart name (openforms), not the alias."""
    make_tgz(tmp_path / "charts", "openforms", "1.12.0", {"image": {"repository": "openformulieren/open-forms"}})
    deps = [{"name": "openforms", "alias": "openformulieren", "version": "1.12.0"}]
    lines = [
        "openformulieren:",
        "  image:",
        '    tag: "3.4.10@sha256:aaaa"',
    ]
    assert (
        libchartrepoandpathresolution.subchart_default_repository(tmp_path, lines, 3, deps)
        == "openformulieren/open-forms"
    )


def test_subchart_default_repository_nested_subpath(tmp_path: Path, libchartrepoandpathresolution: ModuleType):
    make_tgz(
        tmp_path / "charts",
        "zgw-office-addin",
        "0.9.352",
        {
            "frontend": {"image": {"repository": "example/frontend"}},
        },
    )
    deps = [{"name": "zgw-office-addin", "version": "0.9.352"}]
    lines = [
        "zgw-office-addin:",
        "  frontend:",
        "    image:",
        '      tag: "v0.9.352@sha256:aaaa"',
    ]
    assert libchartrepoandpathresolution.subchart_default_repository(tmp_path, lines, 4, deps) == "example/frontend"


def test_subchart_default_repository_unknown_component_returns_none(
    tmp_path: Path, libchartrepoandpathresolution: ModuleType
):
    lines = ["a:", "  image:", '    tag: "1.0.0@sha256:aaaa"']
    assert libchartrepoandpathresolution.subchart_default_repository(tmp_path, lines, 3, []) is None


def test_subchart_default_repository_too_shallow_path_returns_none(
    tmp_path: Path, libchartrepoandpathresolution: ModuleType
):
    lines = ['tag: "1.0.0@sha256:aaaa"']
    assert libchartrepoandpathresolution.subchart_default_repository(tmp_path, lines, 1, [{"name": "a"}]) is None


def test_subchart_default_repository_subchart_has_no_repository_at_path(
    tmp_path: Path, libchartrepoandpathresolution: ModuleType
):
    make_tgz(tmp_path / "charts", "openzaak", "1.14.2", {"image": {}})
    deps = [{"name": "openzaak", "version": "1.14.2"}]
    lines = ["openzaak:", "  image:", '    tag: "1.27.4@sha256:aaaa"']
    assert libchartrepoandpathresolution.subchart_default_repository(tmp_path, lines, 3, deps) is None


def test_subchart_default_repository_caches_across_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    libchartpullandsubchartresolution: ModuleType,
    libchartrepoandpathresolution: ModuleType,
):
    make_tgz(
        tmp_path / "charts",
        "openzaak",
        "1.14.2",
        {
            "image": {"repository": "openzaak/open-zaak"},
            "worker": {"image": {"repository": "openzaak/open-zaak-worker"}},
        },
    )
    deps = [{"name": "openzaak", "version": "1.14.2"}]
    lines = [
        "openzaak:",
        "  image:",
        '    tag: "1.27.4@sha256:aaaa"',
        "  worker:",
        "    image:",
        '      tag: "1.27.4@sha256:bbbb"',
    ]
    calls = []
    real_subchart_values = libchartpullandsubchartresolution.subchart_values

    def spy(chart_dir, dep):
        calls.append(dep["name"])
        return real_subchart_values(chart_dir, dep)

    monkeypatch.setattr(libchartrepoandpathresolution, "subchart_values", spy)
    cache = {}
    assert (
        libchartrepoandpathresolution.subchart_default_repository(tmp_path, lines, 3, deps, cache)
        == "openzaak/open-zaak"
    )
    assert (
        libchartrepoandpathresolution.subchart_default_repository(tmp_path, lines, 6, deps, cache)
        == "openzaak/open-zaak-worker"
    )
    assert calls == ["openzaak"]  # second lookup served from cache, .tgz read only once


# --- chart_version_lockstep_components (self-resolving wrapper) ---


def test_chart_version_lockstep_components_self_resolves_against_real_chart_dir(libchartregisteredpaths: ModuleType):
    """Without an override, chart_dir self-resolves and the real etc/settings.yaml is read."""
    assert libchartregisteredpaths.chart_version_lockstep_components() == frozenset(
        {"kiss-chart", "pabc", "eck-operator", "internetaakafhandeling"}
    )


def test_chart_version_lockstep_components_explicit_override(libchartregisteredpaths: ModuleType, tmp_path: Path):
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc" / "settings.yaml").write_text(
        'component_resolution:\n  chart_version_lockstep_components: ["only-this-one"]\n',
        encoding="utf-8",
    )
    assert libchartregisteredpaths.chart_version_lockstep_components(tmp_path) == frozenset({"only-this-one"})


# --- version_repository_path_for / nested_subchart_name_for / nested_subchart_registered_paths ---


def test_version_repository_path_for_default(libchartnestedsubchartidentity: ModuleType, tmp_path: Path):
    assert libchartnestedsubchartidentity.version_repository_path_for("redis-operator", tmp_path) == (
        "redisOperator.imageName"
    )
    assert libchartnestedsubchartidentity.version_repository_path_for("unregistered", tmp_path) is None


def test_version_repository_path_for_explicit_override(libchartnestedsubchartidentity: ModuleType, tmp_path: Path):
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc" / "settings.yaml").write_text(
        'component_resolution:\n  version_repository_paths:\n    foo-op: "fooOperator.imageName"\n',
        encoding="utf-8",
    )
    assert libchartnestedsubchartidentity.version_repository_path_for("foo-op", tmp_path) == "fooOperator.imageName"
    assert libchartnestedsubchartidentity.version_repository_path_for("redis-operator", tmp_path) is None


def test_version_repository_path_for_none_chart_dir_returns_none(libchartnestedsubchartidentity: ModuleType):
    """chart_dir=None (reachable via full_repository_for_path) returns None, never crashes."""
    assert libchartnestedsubchartidentity.version_repository_path_for("redis-operator", None) is None


def test_nested_subchart_name_for_default(libchartnestedsubchartidentity: ModuleType, tmp_path: Path):
    assert (
        libchartnestedsubchartidentity.nested_subchart_name_for("eck-stack", "eck-elasticsearch.version", tmp_path)
        == "eck-elasticsearch"
    )
    assert (
        libchartnestedsubchartidentity.nested_subchart_name_for("eck-stack", "unregistered.version", tmp_path) is None
    )


def test_nested_subchart_name_for_explicit_override(libchartnestedsubchartidentity: ModuleType, tmp_path: Path):
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc" / "settings.yaml").write_text(
        "component_resolution:\n"
        "  version_path_nested_subcharts:\n"
        "    eck-stack:\n"
        "      eck-elasticsearch.version: only-this-one\n",
        encoding="utf-8",
    )
    assert (
        libchartnestedsubchartidentity.nested_subchart_name_for("eck-stack", "eck-elasticsearch.version", tmp_path)
        == "only-this-one"
    )
    assert libchartnestedsubchartidentity.nested_subchart_name_for("eck-stack", "eck-kibana.version", tmp_path) is None


def test_nested_subchart_name_for_none_chart_dir_returns_none(libchartnestedsubchartidentity: ModuleType):
    assert (
        libchartnestedsubchartidentity.nested_subchart_name_for("eck-stack", "eck-elasticsearch.version", None) is None
    )


def test_nested_subchart_registered_paths_self_resolves_against_real_chart_dir(
    libchartnestedsubchartidentity: ModuleType,
):
    """Without an override, chart_dir self-resolves and the real etc/settings.yaml is read."""
    assert sorted(libchartnestedsubchartidentity.nested_subchart_registered_paths("eck-stack")) == sorted(
        ["eck-elasticsearch.version", "eck-kibana.version", "eck-enterprise-search.version"]
    )
    assert libchartnestedsubchartidentity.nested_subchart_registered_paths("unregistered") == []


def test_nested_subchart_registered_paths_explicit_override(libchartnestedsubchartidentity: ModuleType, tmp_path: Path):
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc" / "settings.yaml").write_text(
        "component_resolution:\n"
        "  version_path_nested_subcharts:\n"
        "    eck-stack:\n"
        "      eck-elasticsearch.version: eck-elasticsearch\n",
        encoding="utf-8",
    )
    assert libchartnestedsubchartidentity.nested_subchart_registered_paths("eck-stack", tmp_path) == [
        "eck-elasticsearch.version"
    ]


# --- component_image_paths / image_paths_for (self-resolving wrappers) ---


def test_component_image_paths_self_resolves_against_real_chart_dir(libchartregisteredpaths: ModuleType):
    """Without an override, chart_dir self-resolves and the real etc/settings.yaml is read."""
    assert libchartregisteredpaths.component_image_paths() == {
        "zgw-office-addin": ["frontend.image", "backend.image"],
        "keycloak-operator": ["operator.image"],
        "openbao": ["server.image", "configuration.job.image"],
        "internetaakafhandeling": ["web.image", "poller.image"],
        "kiss-chart": ["image", "settings.syncJobs.image"],
        "pabc": ["image", "migrations.image"],
        "eck-operator": ["image"],
    }


def test_component_image_paths_explicit_override(libchartregisteredpaths: ModuleType, tmp_path: Path):
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc" / "settings.yaml").write_text(
        'component_resolution:\n  image_paths:\n    only-this-one: ["image"]\n',
        encoding="utf-8",
    )
    assert libchartregisteredpaths.component_image_paths(tmp_path) == {"only-this-one": ["image"]}


def test_image_paths_for_self_resolves_against_real_chart_dir(libchartregisteredpaths: ModuleType):
    """Self-resolving default via the per-component accessor, registered and unregistered."""
    assert libchartregisteredpaths.image_paths_for("zgw-office-addin") == ["frontend.image", "backend.image"]
    assert libchartregisteredpaths.image_paths_for("zac") == ["image"]


def test_image_paths_for_explicit_override(libchartregisteredpaths: ModuleType, tmp_path: Path):
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc" / "settings.yaml").write_text(
        "component_resolution:\n"
        "  image_paths:\n"
        '    only-this-one: ["frontend.image", "backend.image"]\n'
        '  default_image_paths: ["custom-default-image"]\n',
        encoding="utf-8",
    )
    assert libchartregisteredpaths.image_paths_for("only-this-one", tmp_path) == ["frontend.image", "backend.image"]
    assert libchartregisteredpaths.image_paths_for("unregistered", tmp_path) == ["custom-default-image"]


# --- component_version_paths / version_paths_for (self-resolving wrappers) ---


def test_component_version_paths_self_resolves_against_real_chart_dir(libchartregisteredpaths: ModuleType):
    """Self-resolving default for the bare-version-field registry."""
    assert libchartregisteredpaths.component_version_paths() == {
        "eck-stack": ["eck-elasticsearch.version", "eck-kibana.version"],
        "redis-operator": ["redisOperator.imageTag"],
    }


def test_component_version_paths_explicit_override(libchartregisteredpaths: ModuleType, tmp_path: Path):
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc" / "settings.yaml").write_text(
        'component_resolution:\n  version_paths:\n    only-this-one: ["some.version"]\n',
        encoding="utf-8",
    )
    assert libchartregisteredpaths.component_version_paths(tmp_path) == {"only-this-one": ["some.version"]}


def test_version_paths_for_self_resolves_against_real_chart_dir(libchartregisteredpaths: ModuleType):
    assert libchartregisteredpaths.version_paths_for("eck-stack") == ["eck-elasticsearch.version", "eck-kibana.version"]
    assert libchartregisteredpaths.version_paths_for("unregistered") == []


def test_version_paths_for_explicit_override(libchartregisteredpaths: ModuleType, tmp_path: Path):
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc" / "settings.yaml").write_text(
        'component_resolution:\n  version_paths:\n    only-this-one: ["some.version"]\n',
        encoding="utf-8",
    )
    assert libchartregisteredpaths.version_paths_for("only-this-one", tmp_path) == ["some.version"]
    assert libchartregisteredpaths.version_paths_for("redis-operator", tmp_path) == []
