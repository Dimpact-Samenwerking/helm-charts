"""ChartImageIndex: one chart state's paths and the maps built from them."""

from pathlib import Path

from lib.chart.chart_yaml import ChartDependency
from lib.chart.registered_paths import is_primary_rel_path
from lib.upgradedoc.chart_image_index import ChartImageIndex
from lib.yaml_types import YamlMapping

DEPS: list[ChartDependency] = [{"name": "redis-operator", "version": "0.26.1"}]
VALUES: YamlMapping = {
    "global": {"images": {"curl": {"repository": "curlimages/curl", "tag": "8.22.0@sha256:aaaa"}}},
    "redis-operator": {
        "redisOperator": {"imageTag": "v0.26.0"},
        "redisExporter": {"image": {"repository": "quay.io/opstree/redis-exporter", "tag": "v1.89.0@sha256:bbbb"}},
    },
}


def test_paths_cover_image_tags_bare_version_fields_and_global_anchors(tmp_path: Path):
    index = ChartImageIndex(tmp_path, DEPS, VALUES)

    assert index.paths == {
        ("global", "images", "curl"): "8.22.0@sha256:aaaa",
        ("redis-operator", "redisOperator", "imageTag"): "v0.26.0",
        ("redis-operator", "redisExporter", "image"): "v1.89.0@sha256:bbbb",
    }


def test_a_bare_version_field_is_a_primary_path_not_a_sidecar():
    """canonical_sidecar_row_names classifies with this, so a full path set never names a primary as a sidecar."""
    assert is_primary_rel_path("redis-operator", "redisOperator.imageTag")
    assert not is_primary_rel_path("redis-operator", "redisExporter.image")


def test_repo_map_has_one_representative_per_repository(tmp_path: Path):
    index = ChartImageIndex(tmp_path, DEPS, VALUES)

    assert index.repo_map["opstree/redis-exporter"] == ("redis-operator", "redisExporter", "image")
    assert set(index.repo_map) == set(index.repo_groups)


def test_no_values_gives_empty_maps(tmp_path: Path):
    index = ChartImageIndex(tmp_path, DEPS, None)

    assert (index.paths, index.repo_groups, index.repo_map, index.canonical_names) == ({}, {}, {}, {})
