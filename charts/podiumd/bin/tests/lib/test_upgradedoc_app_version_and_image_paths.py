"""lib.upgradedoc -- app-version lookup and image/version tag path discovery."""

from pathlib import Path
from types import ModuleType

import pytest

# --- actual_app_version ---


def test_actual_app_version_single_image(libupgradedocappversion: ModuleType):
    assert libupgradedocappversion.actual_app_version({"zac": {"image": {"tag": "5.4.3@sha256:abc"}}}, "zac") == "5.4.3"


def test_actual_app_version_frontend_backend_lockstep(libupgradedocappversion: ModuleType):
    values = {"zgw-office-addin": {"frontend": {"image": {"tag": "v0.9.352@sha256:abc"}}}}
    assert libupgradedocappversion.actual_app_version(values, "zgw-office-addin") == "v0.9.352"


def test_actual_app_version_missing_returns_none(libupgradedocappversion: ModuleType):
    assert libupgradedocappversion.actual_app_version({}, "missing") is None


def test_actual_app_version_uses_component_for_aliased_registry_lookup(libupgradedocappversion: ModuleType):
    # image_paths entries are keyed by dependency name, not the values.yaml alias.
    values = {"kc": {"operator": {"image": {"tag": "26.7.2@sha256:abc"}}}}
    assert libupgradedocappversion.actual_app_version(values, "kc", "keycloak-operator") == "26.7.2"
    assert libupgradedocappversion.actual_app_version(values, "kc") is None


def test_actual_app_version_falls_back_to_bare_version_field(libupgradedocappversion: ModuleType):
    """eck-stack's app version is a bare "version:" field, found via the COMPONENT_VERSION_PATHS fallback."""
    values = {"kiss-eck": {"eck-elasticsearch": {"version": "8.19.19"}}}
    assert libupgradedocappversion.actual_app_version(values, "kiss-eck", "eck-stack") == "8.19.19"


def test_actual_app_version_falls_back_to_split_image_tag_field(libupgradedocappversion: ModuleType):
    """redis-operator uses sibling "imageName"/"imageTag" fields, found via the COMPONENT_VERSION_PATHS fallback."""
    values = {
        "redis-operator": {"redisOperator": {"imageName": "quay.io/opstree/redis-operator", "imageTag": "v0.26.0"}}
    }
    assert libupgradedocappversion.actual_app_version(values, "redis-operator") == "v0.26.0"


def test_actual_app_version_image_tag_path_tried_before_version_path(
    libupgradedocappversion: ModuleType, monkeypatch: pytest.MonkeyPatch
):
    """version_paths_for is only consulted when no image_paths_for candidate resolves."""
    monkeypatch.setattr(
        libupgradedocappversion,
        "version_paths_for",
        lambda component, chart_dir=None: {"widget": ["fallback.version"]}.get(component, []),
    )
    values = {"widget": {"image": {"tag": "1.0.0@sha256:abc"}, "fallback": {"version": "9.9.9"}}}
    assert libupgradedocappversion.actual_app_version(values, "widget") == "1.0.0"


def _make_vendored_tgz(charts_dir, name, version, values, chart_yaml):
    import io
    import tarfile

    import yaml

    charts_dir.mkdir(parents=True, exist_ok=True)
    tgz_path = charts_dir / f"{name}-{version}.tgz"
    with tarfile.open(tgz_path, "w:gz") as tar:
        for filename, content in ((f"{name}/values.yaml", values), (f"{name}/Chart.yaml", chart_yaml)):
            data = yaml.safe_dump(content).encode("utf-8")
            info = tarfile.TarInfo(name=filename)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return tgz_path


def test_actual_app_version_falls_back_to_vendored_subchart_app_version(
    libupgradedocappversion: ModuleType, tmp_path: Path
):
    """openbao's blank tag resolves to the vendored Chart.yaml appVersion, only when chart_dir/dep are given."""
    _make_vendored_tgz(
        tmp_path / "charts",
        "openbao",
        "0.28.4",
        {"server": {"image": {"tag": ""}}},
        {"apiVersion": "v2", "version": "0.28.4", "appVersion": "v2.5.5"},
    )
    values = {"openbao": {"server": {"image": {"repository": "quay.io/openbao/openbao", "tag": ""}}}}
    dep = {"name": "openbao", "version": "0.28.4"}

    assert libupgradedocappversion.actual_app_version(values, "openbao", "openbao") is None
    assert (
        libupgradedocappversion.actual_app_version(values, "openbao", "openbao", chart_dir=tmp_path, dep=dep)
        == "v2.5.5"
    )


def test_actual_app_version_subchart_fallback_only_for_registered_components(
    libupgradedocappversion: ModuleType, tmp_path: Path
):
    """The vendored-appVersion fallback only applies to registered components.

    For an unregistered one a blank tag may mean the image isn't used. A
    synthetic name keeps this test from going stale when components get registered.
    """
    _make_vendored_tgz(
        tmp_path / "charts",
        "totally-unregistered-component",
        "3.5.0",
        {"image": {"tag": ""}},
        {"apiVersion": "v2", "version": "3.5.0", "appVersion": "3.5.0"},
    )
    values = {
        "totally-unregistered-component": {
            "image": {"repository": "example.invalid/totally-unregistered-component", "tag": ""}
        }
    }
    dep = {"name": "totally-unregistered-component", "version": "3.5.0"}

    assert (
        libupgradedocappversion.actual_app_version(
            values, "totally-unregistered-component", "totally-unregistered-component", chart_dir=tmp_path, dep=dep
        )
        is None
    )


def test_actual_app_version_eck_operator_vendored_fallback_resolves_correctly(
    libupgradedocappversion: ModuleType, tmp_path: Path
):
    """eck-operator without an "image:" override resolves via the vendored appVersion.

    Regression: returning None rendered it as "(new)" instead of "(unchanged)" in upgrade docs.
    """
    _make_vendored_tgz(
        tmp_path / "charts",
        "eck-operator",
        "3.5.0",
        {"image": {"tag": ""}},
        {"apiVersion": "v2", "version": "3.5.0", "appVersion": "3.5.0"},
    )
    values = {"eck-operator": {}}  # no "image:" override, as in the 4.9.1 baseline
    dep = {"name": "eck-operator", "version": "3.5.0"}

    assert (
        libupgradedocappversion.actual_app_version(values, "eck-operator", "eck-operator", chart_dir=tmp_path, dep=dep)
        == "3.5.0"
    )


# --- find_image_tag_paths ---


def test_find_image_tag_paths_finds_nested_images(libupgradedocappversion: ModuleType):
    values = {
        "zac": {
            "image": {"tag": "5.1.0@sha256:aaaa"},
            "opa": {"image": {"tag": "1.19.0-static@sha256:bbbb"}},
        },
    }
    paths = dict(libupgradedocappversion.find_image_tag_paths(values))
    assert paths[("zac", "image")] == "5.1.0@sha256:aaaa"
    assert paths[("zac", "opa", "image")] == "1.19.0-static@sha256:bbbb"


def test_find_image_tag_paths_ignores_tagless_image_blocks(libupgradedocappversion: ModuleType):
    values = {"zac": {"image": {"repository": "x"}}}
    assert dict(libupgradedocappversion.find_image_tag_paths(values)) == {}


def test_find_image_tag_paths_walks_lists(libupgradedocappversion: ModuleType):
    values = {"items": [{"image": {"tag": "1.0@sha256:aaaa"}}]}
    paths = dict(libupgradedocappversion.find_image_tag_paths(values))
    assert paths[("items", "0", "image")] == "1.0@sha256:aaaa"


def test_find_image_tag_paths_finds_suffixed_image_key(libupgradedocappversion: ModuleType):
    """Keys ending in "Image" (e.g. "initImage") count as image blocks too."""
    values = {
        "keycloak-operator": {
            "jobs": {
                "ensurePodiumdAdminUser": {
                    "image": {"tag": "16-alpine@sha256:aaaa"},
                    "initImage": {"tag": "3.14.7-slim@sha256:bbbb"},
                }
            }
        }
    }
    paths = dict(libupgradedocappversion.find_image_tag_paths(values))
    assert paths[("keycloak-operator", "jobs", "ensurePodiumdAdminUser", "image")] == "16-alpine@sha256:aaaa"
    assert paths[("keycloak-operator", "jobs", "ensurePodiumdAdminUser", "initImage")] == "3.14.7-slim@sha256:bbbb"


def test_find_image_tag_paths_excludes_plural_images_container(libupgradedocappversion: ModuleType):
    """The plural "images" container is not itself an image block."""
    values = {"global": {"images": {"nginx": {"tag": "1.31.4@sha256:aaaa"}}}}
    assert dict(libupgradedocappversion.find_image_tag_paths(values)) == {}


# --- find_image_tag_paths: include_null_tags ---


def test_find_image_tag_paths_default_still_ignores_null_tag(libupgradedocappversion: ModuleType):
    """include_null_tags defaults to False: null tags are skipped."""
    values = {"eck-operator": {"image": {"repository": "docker.elastic.co/eck/eck-operator", "tag": None}}}
    assert dict(libupgradedocappversion.find_image_tag_paths(values)) == {}


def test_find_image_tag_paths_include_null_tags_yields_none_for_null_tag_with_repository(
    libupgradedocappversion: ModuleType,
):
    values = {"eck-operator": {"image": {"repository": "docker.elastic.co/eck/eck-operator", "tag": None}}}
    paths = dict(libupgradedocappversion.find_image_tag_paths(values, include_null_tags=True))
    assert paths == {("eck-operator", "image"): None}


def test_find_image_tag_paths_include_null_tags_yields_none_for_missing_tag_key(libupgradedocappversion: ModuleType):
    """A missing "tag:" key is treated like an explicit null, as Helm does."""
    values = {"eck-operator": {"image": {"repository": "docker.elastic.co/eck/eck-operator"}}}
    paths = dict(libupgradedocappversion.find_image_tag_paths(values, include_null_tags=True))
    assert paths == {("eck-operator", "image"): None}


def test_find_image_tag_paths_include_null_tags_skips_block_with_no_repository(libupgradedocappversion: ModuleType):
    """A null tag without a repository has nothing to resolve, so it's not yielded."""
    values = {"eck-operator": {"image": {"tag": None}}}
    assert dict(libupgradedocappversion.find_image_tag_paths(values, include_null_tags=True)) == {}


def test_find_image_tag_paths_include_null_tags_still_excludes_blank_string_tag(libupgradedocappversion: ModuleType):
    """A blank-string tag (openbao) stays excluded; it is not a null tag."""
    values = {"openbao": {"server": {"image": {"repository": "openbao/openbao", "tag": ""}}}}
    assert dict(libupgradedocappversion.find_image_tag_paths(values, include_null_tags=True)) == {}


def test_find_image_tag_paths_include_null_tags_does_not_affect_real_tags(libupgradedocappversion: ModuleType):
    """Real tags in the same tree are unaffected by include_null_tags."""
    values = {
        "eck-operator": {"image": {"repository": "docker.elastic.co/eck/eck-operator", "tag": None}},
        "zac": {"image": {"tag": "5.1.0@sha256:aaaa"}},
    }
    paths = dict(libupgradedocappversion.find_image_tag_paths(values, include_null_tags=True))
    assert paths[("zac", "image")] == "5.1.0@sha256:aaaa"
    assert paths[("eck-operator", "image")] is None


# --- find_component_version_tags / find_all_image_and_version_paths ---
# Flat version fields (e.g. redisOperator.imageTag) are invisible to
# find_image_tag_paths; missing them hid real bumps from the list-diff check.


def test_find_component_version_tags_finds_registered_bare_field(libupgradedocappversion: ModuleType):
    deps = [{"name": "redis-operator", "version": "0.26.1"}]
    values = {
        "redis-operator": {
            "redisOperator": {
                "imageName": "quay.io/opstree/redis-operator",
                "imageTag": "v0.26.0@sha256:aaaa",
            }
        }
    }
    paths = dict(libupgradedocappversion.find_component_version_tags(values, deps))
    assert paths[("redis-operator", "redisOperator", "imageTag")] == "v0.26.0@sha256:aaaa"


def test_find_component_version_tags_uses_alias_not_name_for_the_values_key(libupgradedocappversion: ModuleType):
    deps = [{"name": "eck-stack", "alias": "kiss-eck", "version": "0.20.0"}]
    values = {"kiss-eck": {"eck-elasticsearch": {"version": "8.19.19"}, "eck-kibana": {"version": "8.19.19"}}}
    paths = dict(libupgradedocappversion.find_component_version_tags(values, deps))
    assert paths[("kiss-eck", "eck-elasticsearch", "version")] == "8.19.19"
    assert paths[("kiss-eck", "eck-kibana", "version")] == "8.19.19"


def test_find_component_version_tags_skips_unset_field(libupgradedocappversion: ModuleType):
    deps = [{"name": "redis-operator", "version": "0.26.1"}]
    values = {"redis-operator": {}}
    assert dict(libupgradedocappversion.find_component_version_tags(values, deps)) == {}


def test_find_component_version_tags_includes_nested_subchart_registered_field(libupgradedocappversion: ModuleType):
    """Fields registered only in COMPONENT_VERSION_PATH_NESTED_SUBCHARTS are found too."""
    deps = [{"name": "eck-stack", "alias": "kiss-eck", "version": "0.20.0"}]
    values = {"kiss-eck": {"eck-enterprise-search": {"version": "8.19.19"}}}
    paths = dict(libupgradedocappversion.find_component_version_tags(values, deps))
    assert paths[("kiss-eck", "eck-enterprise-search", "version")] == "8.19.19"


def test_find_component_version_tags_ignores_unregistered_dependency(libupgradedocappversion: ModuleType):
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.297"}]
    values = {"zac": {"image": {"tag": "5.4.4@sha256:aaaa"}}}
    assert dict(libupgradedocappversion.find_component_version_tags(values, deps)) == {}


def test_find_all_image_and_version_paths_combines_both(libupgradedocappversion: ModuleType):
    deps = [{"name": "redis-operator", "version": "0.26.1"}]
    values = {
        "redis-operator": {
            "redisOperator": {"imageName": "quay.io/opstree/redis-operator", "imageTag": "v0.26.0@sha256:aaaa"},
            "redis-ha": {"image": {"tag": "8.6.6@sha256:bbbb"}},
        }
    }
    paths = dict(libupgradedocappversion.find_all_image_and_version_paths(values, deps))
    assert paths[("redis-operator", "redisOperator", "imageTag")] == "v0.26.0@sha256:aaaa"
    assert paths[("redis-operator", "redis-ha", "image")] == "8.6.6@sha256:bbbb"


# --- resolve_entry_path ---


def test_resolve_entry_path_exact_match(libupgradedocappversion: ModuleType):
    paths = [("zac",), ("zgw-office-addin", "frontend"), ("zgw-office-addin", "backend")]
    assert libupgradedocappversion.resolve_entry_path("zgw-office-addin-frontend", paths) == (
        "zgw-office-addin",
        "frontend",
    )


def test_resolve_entry_path_last_word_must_match(libupgradedocappversion: ModuleType):
    paths = [("zac", "solr-operator", "solr"), ("zac", "solr-operator", "zookeeper-operator", "zookeeper")]
    assert libupgradedocappversion.resolve_entry_path("zac-solr", paths) == ("zac", "solr-operator", "solr")


def test_resolve_entry_path_no_match_returns_none(libupgradedocappversion: ModuleType):
    assert libupgradedocappversion.resolve_entry_path("totally-unrelated", [("zac",)]) is None


def test_resolve_entry_path_ignores_trailing_image_key_for_matching(libupgradedocappversion: ModuleType):
    """The trailing image key is skipped for "last word must match" but kept in the result."""
    paths = [("zac", "opa", "image")]
    assert libupgradedocappversion.resolve_entry_path("opa", paths) == ("zac", "opa", "image")


def test_resolve_entry_path_ignores_trailing_suffixed_image_key(libupgradedocappversion: ModuleType):
    paths = [("keycloak-operator", "python", "initImage")]
    assert libupgradedocappversion.resolve_entry_path("python", paths) == ("keycloak-operator", "python", "initImage")


# --- resolve_entry_image_path ---


def test_resolve_entry_image_path_exact_repo_map_hit(libupgradedocappversion: ModuleType):
    """repo_map resolves names that word matching can't (e.g. zaakafhandelcomponent -> zac)."""
    paths = [("zac",)]
    repo_map = {"infonl/zaakafhandelcomponent": ("zac",)}
    entry = {"name": "infonl/zaakafhandelcomponent", "url": "ghcr.io/infonl/zaakafhandelcomponent"}
    assert libupgradedocappversion.resolve_entry_image_path(entry["name"], paths, repo_map) == ("zac",)


def test_resolve_entry_image_path_falls_back_without_repo_map(libupgradedocappversion: ModuleType):
    """Without repo_map it behaves like resolve_entry_path."""
    paths = [("zac",)]
    entry = {"name": "zac"}
    assert libupgradedocappversion.resolve_entry_image_path(entry["name"], paths) == ("zac",)


def test_resolve_entry_image_path_falls_back_when_repo_map_has_no_hit(libupgradedocappversion: ModuleType):
    """A repo_map miss (e.g. a nested sidecar) falls back to word matching."""
    paths = [("zac", "opa", "image")]
    repo_map = {"infonl/zaakafhandelcomponent": ("zac",)}
    entry = {"name": "opa", "url": "docker.io/openpolicyagent/opa"}
    assert libupgradedocappversion.resolve_entry_image_path(entry["name"], paths, repo_map) == ("zac", "opa", "image")


def test_resolve_entry_image_path_ignores_repo_map_hit_not_in_paths(libupgradedocappversion: ModuleType):
    """A repo_map hit absent from paths (e.g. not in baseline) is ignored."""
    paths = [("unrelated",)]
    repo_map = {"infonl/zaakafhandelcomponent": ("zac",)}
    entry = {"name": "infonl/zaakafhandelcomponent"}
    assert libupgradedocappversion.resolve_entry_image_path(entry["name"], paths, repo_map) is None
