"""lib.chart — canonical sidecar row naming, subchart template text/
default-repository resolution, and the self-resolving registry wrappers:
canonical_sidecar_row_names, subchart_template_text,
subchart_default_repository, chart_version_lockstep_components,
version_repository_path_for, nested_subchart_name_for,
nested_subchart_registered_paths, component_image_paths, image_paths_for,
component_version_paths, version_paths_for. Split out of the former
test_chart.py (see the other test_chart_*.py files for the rest)."""

import io
import tarfile

import yaml


def make_tgz(charts_dir, name, version, values, templates=None, chart_yaml=None, raw_files=None):
    """A minimal vendored <name>-<version>.tgz containing <name>/values.yaml
    and, if `templates` is given (a {filename: text} dict), <name>/templates/
    <filename> for each entry — enough to exercise subchart_values/
    subchart_default_repository/subchart_template_text without a real
    `helm pull`. `chart_yaml`, if given (a dict), is ALSO written as
    <name>/Chart.yaml — for subchart_app_version. `raw_files`, if given
    (a {internal tar path: text} dict, paths relative to the tgz root —
    e.g. "<name>/charts/<nested>/values.yaml"), writes each verbatim —
    for nested_subchart_raw_text/nested_subchart_documented_image_
    repository, where the content isn't real structured YAML (a
    commented-out example line) so yaml.safe_dump can't produce it."""
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


def test_canonical_sidecar_row_names_dependency_sidecar(libchart, tmp_path):
    dep = {"name": "redis-operator", "alias": "", "version": "0.26.0"}
    values = {"redis-operator": {"redis-ha": {"image": {"repository": "quay.io/opstree/redis"}}}}
    paths = [("redis-operator", "redis-ha", "image")]

    names = libchart.canonical_sidecar_row_names(tmp_path, [dep], values, paths, allow_pull=False)

    assert names == {"redis-operator - redis": ("redis-operator", "redis-ha", "image")}


def test_canonical_sidecar_row_names_native_component_sidecar(libchart, tmp_path):
    """frankgateway (see lib.chart.NATIVE_COMPONENTS) has no Chart.yaml
    dependency at all — deps is empty on purpose — but it's still the
    real owner of its own nested sidecar images, the same as a real
    dependency is of its own."""
    values = {"frankgateway": {"etcd": {"image": {"repository": "quay.io/coreos/etcd"}}}}
    paths = [("frankgateway", "etcd", "image")]

    names = libchart.canonical_sidecar_row_names(tmp_path, [], values, paths, allow_pull=False)

    assert names == {"frankgateway - etcd": ("frankgateway", "etcd", "image")}


def test_canonical_sidecar_row_names_excludes_native_components_own_primary_image(libchart, tmp_path):
    """Same exclusion as a real dependency's own primary image — frankgateway's
    OWN top-level image is not a sidecar of itself."""
    values = {"frankgateway": {"image": {"repository": "ghcr.io/wearefrank/frank-gateway"}}}
    paths = [("frankgateway", "image")]

    names = libchart.canonical_sidecar_row_names(tmp_path, [], values, paths, allow_pull=False)

    assert names == {}


def test_canonical_sidecar_row_names_excludes_dependencys_own_primary_image(libchart, tmp_path):
    """The dependency's own registered primary image (image_paths_for) is
    NOT a sidecar — match_dependency already covers it by the
    dependency's plain name/alias, so it must not show up here too."""
    dep = {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}
    values = {"zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent"}}}
    paths = [("zac", "image")]

    names = libchart.canonical_sidecar_row_names(tmp_path, [dep], values, paths, allow_pull=False)

    assert names == {}


def test_canonical_sidecar_row_names_self_referential_basename_falls_back_to_path_segment(libchart, tmp_path):
    """A nested image whose OWN repository basename happens to equal the
    parent dependency's own values key (real case: keycloak-operator.
    operator.image, the operator's own container — NOT registered in
    COMPONENT_IMAGE_PATHS, unlike operator.config.keycloakImage) must
    never produce a "<key> - <key>" canonical name — that reads as a
    confusing repeat, not a real distinct-image name. Falls back to the
    values-tree path's own second-to-last segment instead ("operator"),
    giving "keycloak-operator - operator" — distinct from "this IS the
    dependency's own row" (match_dependency already covers that case by
    the bare dependency name), and clearly still identifies which
    nested image this is."""
    dep = {"name": "keycloak-operator", "alias": "", "version": "1.12.1"}
    values = {"keycloak-operator": {"operator": {"image": {"repository": "quay.io/keycloak/keycloak-operator"}}}}
    paths = [("keycloak-operator", "operator", "image")]

    names = libchart.canonical_sidecar_row_names(tmp_path, [dep], values, paths, allow_pull=False)

    assert names == {"keycloak-operator - operator": ("keycloak-operator", "operator", "image")}


def test_canonical_sidecar_row_names_self_referential_basename_no_fallback_segment_is_excluded(libchart, tmp_path):
    """When the self-referential path has nothing but the top-level key
    and the final image key itself (no distinct segment in between to
    fall back to), there's no useful alternative name at all — still
    excluded entirely, same as before this fallback existed."""
    dep = {"name": "keycloak-operator", "alias": "", "version": "1.12.1"}
    values = {"keycloak-operator": {"image": {"repository": "quay.io/keycloak/keycloak-operator"}}}
    paths = [("keycloak-operator", "image")]

    names = libchart.canonical_sidecar_row_names(tmp_path, [dep], values, paths, allow_pull=False)

    assert names == {}


def test_canonical_sidecar_row_names_global_shared_image(libchart, tmp_path):
    """A "global"-rooted image has no single owning dependency at all —
    the canonical name is bare "<basename>" (update-image-version's
    MULTIPLE_KEY convention), never "<values_key> - <basename>"."""
    values = {"global": {"images": {"nginx": {"image": {"repository": "docker.io/nginxinc/nginx-unprivileged"}}}}}
    paths = [("global", "images", "nginx", "image")]

    names = libchart.canonical_sidecar_row_names(tmp_path, [], values, paths, allow_pull=False)

    assert names == {"nginx-unprivileged": ("global", "images", "nginx", "image")}


def test_canonical_sidecar_row_names_excludes_sidecar_sharing_a_global_repository(libchart, tmp_path):
    """Real bug: zac's own nginx sidecar and frankgateway's own nginx
    sidecar both alias the exact same global.images.nginx anchor — each
    independently registering its own "<dep> - nginx-unprivileged" name
    gave the SAME version bump two separate, equally-valid-looking
    canonical names ("zac - nginx-unprivileged" AND "frankgateway -
    nginx-unprivileged" both showing up as separate -upgrade.md rows).
    Only the bare "global" name should ever be registered for this
    shared repository — the per-component ones are excluded entirely,
    not just deprioritized."""
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

    names = libchart.canonical_sidecar_row_names(tmp_path, deps, values, paths, allow_pull=False)

    assert names == {"nginx-unprivileged": ("global", "images", "nginx")}


def test_canonical_sidecar_row_names_multiple_sidecars_stay_distinct(libchart, tmp_path):
    values = {
        "redis-operator": {
            "redis-ha": {"image": {"repository": "quay.io/opstree/redis"}},
            "redis-exporter": {"image": {"repository": "quay.io/opstree/redis-exporter"}},
        }
    }
    dep = {"name": "redis-operator", "alias": "", "version": "0.26.0"}
    paths = [("redis-operator", "redis-ha", "image"), ("redis-operator", "redis-exporter", "image")]

    names = libchart.canonical_sidecar_row_names(tmp_path, [dep], values, paths, allow_pull=False)

    assert names == {
        "redis-operator - redis": ("redis-operator", "redis-ha", "image"),
        "redis-operator - redis-exporter": ("redis-operator", "redis-exporter", "image"),
    }


# --- subchart_template_text ---


def test_subchart_template_text_concatenates_all_template_files(libchart, tmp_path):
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
    text = libchart.subchart_template_text(tmp_path, dep)
    assert "{{ .Values.image.repository }}" in text
    assert "kind: Service" in text


def test_subchart_template_text_missing_tgz_returns_none(libchart, tmp_path):
    dep = {"name": "pabc", "version": "1.1.1"}
    assert libchart.subchart_template_text(tmp_path, dep) is None


def test_subchart_template_text_no_templates_dir_returns_none(libchart, tmp_path):
    """A .tgz with only values.yaml (no templates/ at all — the shape
    make_tgz produces when `templates` is omitted) is "can't tell", not
    an empty-but-valid haystack — callers must be able to distinguish the
    two, so this returns None rather than ""."""
    make_tgz(tmp_path / "charts", "pabc", "1.1.1", {"image": {"repository": "pabc/pabc-api"}})
    dep = {"name": "pabc", "version": "1.1.1"}
    assert libchart.subchart_template_text(tmp_path, dep) is None


# --- subchart_default_repository ---


def test_subchart_default_repository_resolves_via_alias(libchart, tmp_path):
    """openformulieren is a values.yaml/Chart.yaml alias for the openforms
    subchart — the .tgz and its internal values.yaml are keyed by the
    real chart name, not the alias."""
    make_tgz(tmp_path / "charts", "openforms", "1.12.0", {"image": {"repository": "openformulieren/open-forms"}})
    deps = [{"name": "openforms", "alias": "openformulieren", "version": "1.12.0"}]
    lines = [
        "openformulieren:",
        "  image:",
        '    tag: "3.4.10@sha256:aaaa"',
    ]
    assert libchart.subchart_default_repository(tmp_path, lines, 3, deps) == "openformulieren/open-forms"


def test_subchart_default_repository_nested_subpath(libchart, tmp_path):
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
    assert libchart.subchart_default_repository(tmp_path, lines, 4, deps) == "example/frontend"


def test_subchart_default_repository_unknown_component_returns_none(libchart, tmp_path):
    lines = ["a:", "  image:", '    tag: "1.0.0@sha256:aaaa"']
    assert libchart.subchart_default_repository(tmp_path, lines, 3, []) is None


def test_subchart_default_repository_too_shallow_path_returns_none(libchart, tmp_path):
    lines = ['tag: "1.0.0@sha256:aaaa"']
    assert libchart.subchart_default_repository(tmp_path, lines, 1, [{"name": "a"}]) is None


def test_subchart_default_repository_subchart_has_no_repository_at_path(libchart, tmp_path):
    make_tgz(tmp_path / "charts", "openzaak", "1.14.2", {"image": {}})
    deps = [{"name": "openzaak", "version": "1.14.2"}]
    lines = ["openzaak:", "  image:", '    tag: "1.27.4@sha256:aaaa"']
    assert libchart.subchart_default_repository(tmp_path, lines, 3, deps) is None


def test_subchart_default_repository_caches_across_calls(libchart, tmp_path, monkeypatch):
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
    real_subchart_values = libchart.subchart_values

    def spy(chart_dir, dep):
        calls.append(dep["name"])
        return real_subchart_values(chart_dir, dep)

    monkeypatch.setattr(libchart, "subchart_values", spy)
    cache = {}
    assert libchart.subchart_default_repository(tmp_path, lines, 3, deps, cache) == "openzaak/open-zaak"
    assert libchart.subchart_default_repository(tmp_path, lines, 6, deps, cache) == "openzaak/open-zaak-worker"
    assert calls == ["openzaak"]  # second lookup served from cache, .tgz read only once


# --- chart_version_lockstep_components (self-resolving wrapper) ---


def test_chart_version_lockstep_components_self_resolves_against_real_chart_dir(libchart, libchartregisteredpaths):
    """Called with no override, resolves chart_dir from lib/chart.py's own
    on-disk location (parents[2]) and reads the REAL etc/settings.yaml --
    proves the self-resolving default actually works end to end, not just
    against a synthetic chart_dir handed in by a test."""
    assert libchartregisteredpaths.chart_version_lockstep_components() == frozenset(
        {"kiss-chart", "pabc", "eck-operator"}
    )


def test_chart_version_lockstep_components_explicit_override(libchart, libchartregisteredpaths, tmp_path):
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc" / "settings.yaml").write_text(
        'component_resolution:\n  chart_version_lockstep_components: ["only-this-one"]\n',
        encoding="utf-8",
    )
    assert libchartregisteredpaths.chart_version_lockstep_components(tmp_path) == frozenset({"only-this-one"})


# --- version_repository_path_for / nested_subchart_name_for / nested_subchart_registered_paths ---


def test_version_repository_path_for_default(libchart, tmp_path):
    assert libchart.version_repository_path_for("redis-operator", tmp_path) == "redisOperator.imageName"
    assert libchart.version_repository_path_for("unregistered", tmp_path) is None


def test_version_repository_path_for_explicit_override(libchart, tmp_path):
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc" / "settings.yaml").write_text(
        'component_resolution:\n  version_repository_paths:\n    foo-op: "fooOperator.imageName"\n',
        encoding="utf-8",
    )
    assert libchart.version_repository_path_for("foo-op", tmp_path) == "fooOperator.imageName"
    assert libchart.version_repository_path_for("redis-operator", tmp_path) is None


def test_version_repository_path_for_none_chart_dir_returns_none(libchart):
    """Some of its own call sites (e.g. full_repository_for_path) are
    themselves reachable with chart_dir=None -- must degrade gracefully,
    never crash a report-only check."""
    assert libchart.version_repository_path_for("redis-operator", None) is None


def test_nested_subchart_name_for_default(libchart, tmp_path):
    assert libchart.nested_subchart_name_for("eck-stack", "eck-elasticsearch.version", tmp_path) == "eck-elasticsearch"
    assert libchart.nested_subchart_name_for("eck-stack", "unregistered.version", tmp_path) is None


def test_nested_subchart_name_for_explicit_override(libchart, tmp_path):
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc" / "settings.yaml").write_text(
        "component_resolution:\n"
        "  version_path_nested_subcharts:\n"
        "    eck-stack:\n"
        "      eck-elasticsearch.version: only-this-one\n",
        encoding="utf-8",
    )
    assert libchart.nested_subchart_name_for("eck-stack", "eck-elasticsearch.version", tmp_path) == "only-this-one"
    assert libchart.nested_subchart_name_for("eck-stack", "eck-kibana.version", tmp_path) is None


def test_nested_subchart_name_for_none_chart_dir_returns_none(libchart):
    assert libchart.nested_subchart_name_for("eck-stack", "eck-elasticsearch.version", None) is None


def test_nested_subchart_registered_paths_self_resolves_against_real_chart_dir(libchart):
    """Called with no override, resolves chart_dir the same self-resolving
    way chart_version_lockstep_components does -- proves the default
    works end to end against the REAL etc/settings.yaml, not just a
    synthetic chart_dir handed in by a test."""
    assert sorted(libchart.nested_subchart_registered_paths("eck-stack")) == sorted(
        ["eck-elasticsearch.version", "eck-kibana.version", "eck-enterprise-search.version"]
    )
    assert libchart.nested_subchart_registered_paths("unregistered") == []


def test_nested_subchart_registered_paths_explicit_override(libchart, tmp_path):
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc" / "settings.yaml").write_text(
        "component_resolution:\n"
        "  version_path_nested_subcharts:\n"
        "    eck-stack:\n"
        "      eck-elasticsearch.version: eck-elasticsearch\n",
        encoding="utf-8",
    )
    assert libchart.nested_subchart_registered_paths("eck-stack", tmp_path) == ["eck-elasticsearch.version"]


# --- component_image_paths / image_paths_for (self-resolving wrappers) ---


def test_component_image_paths_self_resolves_against_real_chart_dir(libchart, libchartregisteredpaths):
    """Called with no override, resolves chart_dir from lib/chart.py's own
    on-disk location (parents[2]) and reads the REAL etc/settings.yaml --
    proves the self-resolving default actually works end to end, not just
    against a synthetic chart_dir handed in by a test."""
    assert libchartregisteredpaths.component_image_paths() == {
        "zgw-office-addin": ["frontend.image", "backend.image"],
        "keycloak-operator": ["operator.config.keycloakImage"],
        "openbao": ["server.image"],
        "internetaakafhandeling": ["web.image", "poller.image"],
        "kiss-chart": ["image", "settings.syncJobs.image"],
        "eck-operator": ["image"],
    }


def test_component_image_paths_explicit_override(libchart, libchartregisteredpaths, tmp_path):
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc" / "settings.yaml").write_text(
        'component_resolution:\n  image_paths:\n    only-this-one: ["image"]\n',
        encoding="utf-8",
    )
    assert libchartregisteredpaths.component_image_paths(tmp_path) == {"only-this-one": ["image"]}


def test_image_paths_for_self_resolves_against_real_chart_dir(libchart, libchartregisteredpaths):
    """Same self-resolving proof as component_image_paths above, but
    through the per-component accessor -- both a registered component and
    the unregistered-default fallback."""
    assert libchartregisteredpaths.image_paths_for("zgw-office-addin") == ["frontend.image", "backend.image"]
    assert libchartregisteredpaths.image_paths_for("zac") == ["image"]


def test_image_paths_for_explicit_override(libchart, libchartregisteredpaths, tmp_path):
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


def test_component_version_paths_self_resolves_against_real_chart_dir(libchart, libchartregisteredpaths):
    """Same self-resolving proof as component_image_paths, for the bare-
    version-field registry."""
    assert libchartregisteredpaths.component_version_paths() == {
        "eck-stack": ["eck-elasticsearch.version", "eck-kibana.version"],
        "redis-operator": ["redisOperator.imageTag"],
    }


def test_component_version_paths_explicit_override(libchart, libchartregisteredpaths, tmp_path):
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc" / "settings.yaml").write_text(
        'component_resolution:\n  version_paths:\n    only-this-one: ["some.version"]\n',
        encoding="utf-8",
    )
    assert libchartregisteredpaths.component_version_paths(tmp_path) == {"only-this-one": ["some.version"]}


def test_version_paths_for_self_resolves_against_real_chart_dir(libchart, libchartregisteredpaths):
    assert libchartregisteredpaths.version_paths_for("eck-stack") == ["eck-elasticsearch.version", "eck-kibana.version"]
    assert libchartregisteredpaths.version_paths_for("unregistered") == []


def test_version_paths_for_explicit_override(libchart, libchartregisteredpaths, tmp_path):
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc" / "settings.yaml").write_text(
        'component_resolution:\n  version_paths:\n    only-this-one: ["some.version"]\n',
        encoding="utf-8",
    )
    assert libchartregisteredpaths.version_paths_for("only-this-one", tmp_path) == ["some.version"]
    assert libchartregisteredpaths.version_paths_for("redis-operator", tmp_path) == []
