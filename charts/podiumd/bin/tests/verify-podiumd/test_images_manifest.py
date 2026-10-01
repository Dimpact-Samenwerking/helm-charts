"""parse_changes_block, check_images_manifest_format."""

from pathlib import Path
from types import ModuleType

import yaml

from dep_helpers import make_dep

REAL_MANIFEST = """\
# Baseline: podiumd 4.8.5 (origin/feature/podiumd-4.8.5 @ f27a008).
#   git diff f27a008..HEAD -- charts/podiumd/Chart.yaml charts/podiumd/values.yaml
#
# Images new or changed in podiumd 4.9.0 vs 4.8.5.
#
# Changes:
#   1. ZAC (Zaakafhandelcomponent) 5.0.2 -> 5.4.3 (chart 1.0.297, unchanged).
#      Includes a bump of the ZAC OPA sidecar (openpolicyagent/opa
#      1.17.1-static -> 1.19.0-static). Other sidecars unchanged.
#   2. ZGW Office Add-in v0.9.313 -> 0.11.0 (chart 0.0.89 -> 0.0.92).
#
# See docs/_UPGRADE_PATHS/4.8.5-to-4.9.0-upgrade.md for the operator upgrade notes.

# ZAC — 5.0.2 -> 5.4.3
- name: infonl/zaakafhandelcomponent
  url: ghcr.io/infonl/zaakafhandelcomponent
  version: "5.4.3"
  digest: "sha256:aaa"

# ZAC OPA sidecar — 1.17.1-static -> 1.19.0-static
- name: openpolicyagent/opa
  url: openpolicyagent/opa
  version: "1.19.0-static"
  digest: "sha256:bbb"
"""


def test_parse_changes_block_extracts_all_items(libupgradedoccomments: ModuleType):
    items = libupgradedoccomments.parse_changes_block(REAL_MANIFEST)
    assert len(items) == 2
    assert items[0]["name"] == "ZAC (Zaakafhandelcomponent)"
    assert items[0]["app_source"] == "5.0.2"
    assert items[0]["app"] == "5.4.3"
    assert items[0]["chart_source"] == "1.0.297"
    assert items[0]["chart"] == "1.0.297"
    assert items[1]["name"] == "ZGW Office Add-in"
    assert items[1]["app_source"] == "v0.9.313"
    assert items[1]["app"] == "0.11.0"


def test_parse_changes_block_does_not_mistake_version_continuation_for_new_item(libupgradedoccomments: ModuleType):
    """Regression: "1.17.1-static -> 1.19.0-static" on an indented
    continuation line must not be parsed as a bogus item #17."""
    items = libupgradedoccomments.parse_changes_block(REAL_MANIFEST)
    names = [i["name"] for i in items]
    assert not any("17.1" in n for n in names)


def test_parse_changes_block_no_changes_section(libupgradedoccomments: ModuleType):
    assert libupgradedoccomments.parse_changes_block("# just a header\n# no changes block\n") == []


# --- check_images_manifest_format ---

DEPS = [
    make_dep("zaakafhandelcomponent", "1.0.297", alias="zac"),
    make_dep("zgw-office-addin", "0.0.92"),
]
VALUES = {
    "zac": {
        "image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "5.4.3@sha256:aaa"},
        "opa": {"image": {"repository": "openpolicyagent/opa", "tag": "1.19.0-static@sha256:bbb"}},
    }
}


def test_images_manifest_format_passes_for_consistent_manifest(libimagesmanifest: ModuleType, tmp_path: Path):
    images_path = tmp_path / "images-4.9.0.yaml"
    images_path.write_text(REAL_MANIFEST)
    issues = libimagesmanifest.check_images_manifest_format(
        images_path,
        libimagesmanifest.ManifestCheckContext(
            "4.8.5",
            "4.9.0",
            DEPS,
            VALUES,
            {},
        ),
    )
    assert issues == []


def test_images_manifest_format_missing_file(libimagesmanifest: ModuleType, tmp_path: Path):
    issues = libimagesmanifest.check_images_manifest_format(
        tmp_path / "missing.yaml",
        libimagesmanifest.ManifestCheckContext(
            "4.8.5",
            "4.9.0",
            DEPS,
            VALUES,
            {},
        ),
    )
    assert "does not exist" in issues[0]


def test_images_manifest_format_invalid_yaml(libimagesmanifest: ModuleType, tmp_path: Path):
    images_path = tmp_path / "images-4.9.0.yaml"
    images_path.write_text("- name: zac\n  bad: [\n")
    issues = libimagesmanifest.check_images_manifest_format(
        images_path,
        libimagesmanifest.ManifestCheckContext(
            "4.8.5",
            "4.9.0",
            DEPS,
            VALUES,
            {},
        ),
    )
    assert any("not valid YAML" in i for i in issues)


def test_images_manifest_format_missing_required_keys(libimagesmanifest: ModuleType, tmp_path: Path):
    images_path = tmp_path / "images-4.9.0.yaml"
    images_path.write_text('- name: zac\n  version: "5.4.3"\n')
    issues = libimagesmanifest.check_images_manifest_format(
        images_path,
        libimagesmanifest.ManifestCheckContext(
            "4.8.5",
            "4.9.0",
            DEPS,
            VALUES,
            {},
        ),
    )
    assert any("missing key" in i for i in issues)


def test_images_manifest_format_stale_baseline_header(libimagesmanifest: ModuleType, tmp_path: Path):
    text = REAL_MANIFEST.replace("podiumd 4.8.5", "podiumd 4.8.2").replace("4.9.0 vs 4.8.5", "4.9.0 vs 4.8.2")
    images_path = tmp_path / "images-4.9.0.yaml"
    images_path.write_text(text)
    issues = libimagesmanifest.check_images_manifest_format(
        images_path,
        libimagesmanifest.ManifestCheckContext(
            "4.8.5",
            "4.9.0",
            DEPS,
            VALUES,
            {},
        ),
    )
    assert any('baseline line says "4.8.2"' in i for i in issues)
    assert any('"... vs ..." line says upgrade_docs_baseline "4.8.2"' in i for i in issues)


def test_images_manifest_format_trailing_period_not_captured(libimagesmanifest: ModuleType, tmp_path: Path):
    """Regression: the trailing period in "vs 4.8.5." must not be captured in the version."""
    images_path = tmp_path / "images-4.9.0.yaml"
    images_path.write_text(REAL_MANIFEST)
    issues = libimagesmanifest.check_images_manifest_format(
        images_path,
        libimagesmanifest.ManifestCheckContext(
            "4.8.5",
            "4.9.0",
            DEPS,
            VALUES,
            {},
        ),
    )
    assert not any("4.8.5." in i for i in issues)


def test_images_manifest_format_baseline_line_trailing_period_not_captured(
    libimagesmanifest: ModuleType, tmp_path: Path
):
    """Regression: IMAGES_STUB_TEMPLATE writes "# Baseline: podiumd 4.9.0. Re-verify ...";
    "." is in the capture class, so without .rstrip(".") every scaffolded manifest fails."""
    text = REAL_MANIFEST.replace(
        "# Baseline: podiumd 4.8.5 (origin/feature/podiumd-4.8.5 @ f27a008).",
        "# Baseline: podiumd 4.8.5. Re-verify before release.",
    )
    images_path = tmp_path / "images-4.9.0.yaml"
    images_path.write_text(text)
    issues = libimagesmanifest.check_images_manifest_format(
        images_path,
        libimagesmanifest.ManifestCheckContext(
            "4.8.5",
            "4.9.0",
            DEPS,
            VALUES,
            {},
        ),
    )
    assert not any("4.8.5." in i for i in issues)
    assert not any("baseline line says" in i for i in issues)


def test_images_manifest_format_changes_block_target_mismatch(libimagesmanifest: ModuleType, tmp_path: Path):
    text = REAL_MANIFEST.replace("5.0.2 -> 5.4.3 (chart 1.0.297", "5.0.2 -> 5.9.9 (chart 1.0.297")
    images_path = tmp_path / "images-4.9.0.yaml"
    images_path.write_text(text)
    issues = libimagesmanifest.check_images_manifest_format(
        images_path,
        libimagesmanifest.ManifestCheckContext(
            "4.8.5",
            "4.9.0",
            DEPS,
            VALUES,
            {},
        ),
    )
    assert any("target app" in i and "5.9.9" in i for i in issues)


def test_images_manifest_format_entry_comment_target_mismatch(libimagesmanifest: ModuleType, tmp_path: Path):
    text = REAL_MANIFEST.replace(
        "# ZAC OPA sidecar — 1.17.1-static -> 1.19.0-static",
        "# ZAC OPA sidecar — 1.17.1-static -> 9.9.9-static",
    )
    images_path = tmp_path / "images-4.9.0.yaml"
    images_path.write_text(text)
    issues = libimagesmanifest.check_images_manifest_format(
        images_path,
        libimagesmanifest.ManifestCheckContext(
            "4.8.5",
            "4.9.0",
            DEPS,
            VALUES,
            {},
        ),
    )
    assert any('comment says target "9.9.9-static"' in i for i in issues)


def test_images_manifest_format_missing_entry_comment(libimagesmanifest: ModuleType, tmp_path: Path):
    text = REAL_MANIFEST.replace("# ZAC OPA sidecar — 1.17.1-static -> 1.19.0-static\n", "")
    images_path = tmp_path / "images-4.9.0.yaml"
    images_path.write_text(text)
    issues = libimagesmanifest.check_images_manifest_format(
        images_path,
        libimagesmanifest.ManifestCheckContext(
            "4.8.5",
            "4.9.0",
            DEPS,
            VALUES,
            {},
        ),
    )
    assert any('entry "openpolicyagent/opa" has no preceding comment' in i for i in issues)


ZGW_MANIFEST = """\
# Baseline: podiumd 4.8.5 (origin/feature/podiumd-4.8.5 @ f27a008).
#
# Images new or changed in podiumd 4.9.0 vs 4.8.5.
#
# Changes:
#   1. ZGW Office Add-in v0.9.313 -> v0.9.352 (chart 0.0.89, unchanged).

# ZGW Office Add-in — v0.9.313 -> v0.9.352
- name: infonl/zgw-office-addin-frontend
  url: ghcr.io/infonl/zgw-office-addin-frontend
  version: "v0.9.352"
  digest: "sha256:aaa"

- name: infonl/zgw-office-addin-backend
  url: ghcr.io/infonl/zgw-office-addin-backend
  version: "v0.9.352"
  digest: "sha256:bbb"
"""
ZGW_DEPS = [make_dep("zgw-office-addin", "0.0.89")]
ZGW_VALUES = {
    "zgw-office-addin": {
        "frontend": {"image": {"tag": "v0.9.352@sha256:aaa"}},
        "backend": {"image": {"tag": "v0.9.352@sha256:bbb"}},
    }
}


def test_images_manifest_format_multi_image_component_shares_one_comment(libimagesmanifest: ModuleType, tmp_path: Path):
    """A multi-image component needs one comment for its group; the second entry (blank
    line above) must not be flagged as missing a comment."""
    images_path = tmp_path / "images-4.9.0.yaml"
    images_path.write_text(ZGW_MANIFEST)
    issues = libimagesmanifest.check_images_manifest_format(
        images_path,
        libimagesmanifest.ManifestCheckContext(
            "4.8.5",
            "4.9.0",
            ZGW_DEPS,
            ZGW_VALUES,
            {},
        ),
    )
    assert issues == []


def test_images_manifest_format_source_vs_baseline(libimagesmanifest: ModuleType, tmp_path: Path):
    baseline_values = {"zac": {"opa": {"image": {"tag": "1.17.1-static@sha256:old"}}}}
    images_path = tmp_path / "images-4.9.0.yaml"
    images_path.write_text(REAL_MANIFEST)
    issues = libimagesmanifest.check_images_manifest_format(
        images_path,
        libimagesmanifest.ManifestCheckContext(
            "4.8.5",
            "4.9.0",
            DEPS,
            VALUES,
            baseline_values,
        ),
    )
    assert issues == []


def test_images_manifest_format_source_vs_baseline_mismatch(libimagesmanifest: ModuleType, tmp_path: Path):
    # chart_dir resolves "openpolicyagent/opa" to its values-tree path.
    baseline_values = {"zac": {"opa": {"image": {"tag": "2.0.0-static@sha256:old"}}}}
    (tmp_path / "Chart.yaml").write_text(yaml.safe_dump({"dependencies": DEPS}), encoding="utf-8")
    (tmp_path / "values.yaml").write_text(yaml.safe_dump(VALUES), encoding="utf-8")
    images_path = tmp_path / "images-4.9.0.yaml"
    images_path.write_text(REAL_MANIFEST)
    issues = libimagesmanifest.check_images_manifest_format(
        images_path,
        libimagesmanifest.ManifestCheckContext(
            "4.8.5",
            "4.9.0",
            DEPS,
            VALUES,
            baseline_values,
            chart_dir=tmp_path,
        ),
    )
    assert any('comment says source "1.17.1-static"' in i for i in issues)


# --- list-diff against a COMPONENT_VERSION_PATHS component: redis-operator pins its
# image as flat scalars (redisOperator.imageTag/imageName), invisible to the structural scan ---

REDIS_OPERATOR_DEPS = [make_dep("redis-operator", "0.26.1")]


def redis_operator_values(tag):
    # Unchanged redis sidecar: without it the structural scan finds nothing and the
    # "if baseline_paths and chart_dir is not None" guard skips the check entirely.
    return {
        "redis-operator": {
            "redisOperator": {"imageName": "quay.io/opstree/redis-operator", "imageTag": f"{tag}@sha256:aaa"},
            "redis-ha": {"image": {"repository": "quay.io/opstree/redis", "tag": "8.6.6@sha256:bbb"}},
        }
    }


REDIS_OPERATOR_MANIFEST = """\
# Baseline: podiumd 4.8.5 (test @ 0000000).
#
# Images new or changed in podiumd 4.9.0 vs 4.8.5.
#
# Changes:
#   1. redis-operator 0.25.0 -> 0.26.0 (chart 0.25.0 -> 0.26.1).
#
# See docs/_UPGRADE_PATHS/4.8.5-to-4.9.0-upgrade.md for the operator upgrade notes.

# redis-operator — 0.25.0 -> 0.26.0
- name: opstree/redis-operator
  url: quay.io/opstree/redis-operator
  version: "v0.26.0"
  digest: "sha256:aaa"
"""


def test_images_manifest_format_component_version_path_change_is_recognized(
    libimagesmanifest: ModuleType, tmp_path: Path
):
    (tmp_path / "Chart.yaml").write_text(yaml.safe_dump({"dependencies": REDIS_OPERATOR_DEPS}), encoding="utf-8")
    (tmp_path / "values.yaml").write_text(yaml.safe_dump(redis_operator_values("v0.26.0")), encoding="utf-8")
    images_path = tmp_path / "images-4.9.0.yaml"
    images_path.write_text(REDIS_OPERATOR_MANIFEST)

    issues = libimagesmanifest.check_images_manifest_format(
        images_path,
        libimagesmanifest.ManifestCheckContext(
            "4.8.5",
            "4.9.0",
            REDIS_OPERATOR_DEPS,
            redis_operator_values("v0.26.0"),
            redis_operator_values("v0.25.0"),
            chart_dir=tmp_path,
        ),
    )

    assert not any("did not change" in i for i in issues)
    assert not any("has no entry" in i for i in issues)


def make_nested_subchart_tgz(chart_dir, name, version, nested_charts):
    """Minimal vendored <name>-<version>.tgz with a "<name>/charts/<nested>/values.yaml"
    member per (nested name, values text) pair in `nested_charts`."""
    import tarfile

    from io import BytesIO

    charts_dir = chart_dir / "charts"
    charts_dir.mkdir(parents=True, exist_ok=True)
    tgz_path = charts_dir / f"{name}-{version}.tgz"
    with tarfile.open(tgz_path, "w:gz") as tar:
        data = yaml.safe_dump({}).encode("utf-8")
        info = tarfile.TarInfo(name=f"{name}/values.yaml")
        info.size = len(data)
        tar.addfile(info, BytesIO(data))
        for nested_name, text in nested_charts.items():
            raw = text.encode("utf-8")
            raw_info = tarfile.TarInfo(name=f"{name}/charts/{nested_name}/values.yaml")
            raw_info.size = len(raw)
            tar.addfile(raw_info, BytesIO(raw))


ECK_STACK_DEPS = [make_dep("eck-stack", "0.20.0", alias="kiss-eck")]

ECK_STACK_MANIFEST = """\
# Baseline: podiumd 4.8.5 (test @ 0000000).
#
# Images new or changed in podiumd 4.9.0 vs 4.8.5.
#
# Changes:
#   1. eck-stack 8.19.3 -> 8.19.19 (chart 0.19.0 -> 0.20.0).
#
# See docs/_UPGRADE_PATHS/4.8.5-to-4.9.0-upgrade.md for the operator upgrade notes.

# eck-stack — 8.19.3 -> 8.19.19
- name: elasticsearch/elasticsearch
  url: docker.elastic.co/elasticsearch/elasticsearch
  version: "8.19.19"
  digest: "sha256:aaa"
- name: kibana/kibana
  url: docker.elastic.co/kibana/kibana
  version: "8.19.19"
  digest: "sha256:bbb"
- name: enterprise-search/enterprise-search
  url: docker.elastic.co/enterprise-search/enterprise-search
  version: "8.19.19"
  digest: "sha256:ccc"
"""


def eck_stack_values(version):
    return {
        "kiss-eck": {
            "eck-elasticsearch": {"version": version},
            "eck-kibana": {"version": version},
            "eck-enterprise-search": {"version": version},
        }
    }


def test_images_manifest_format_sidecars_recognized_within_group_by_basename(
    libimagesmanifest: ModuleType, tmp_path: Path
):
    """kibana/enterprise-search share elasticsearch's group header; component_of must
    resolve all three via repo_map, not fuzzy header matching, so none lack a comment."""
    (tmp_path / "Chart.yaml").write_text(yaml.safe_dump({"dependencies": ECK_STACK_DEPS}), encoding="utf-8")
    (tmp_path / "values.yaml").write_text(yaml.safe_dump(eck_stack_values("8.19.19")), encoding="utf-8")
    make_nested_subchart_tgz(
        tmp_path,
        "eck-stack",
        "0.20.0",
        {
            "eck-elasticsearch": "# image: docker.elastic.co/elasticsearch/elasticsearch:9.5.0\n",
            "eck-kibana": "# image: docker.elastic.co/kibana/kibana:9.5.0\n",
            "eck-enterprise-search": "# image: docker.elastic.co/enterprise-search/enterprise-search:8.19.0\n",
        },
    )
    images_path = tmp_path / "images-4.9.0.yaml"
    images_path.write_text(ECK_STACK_MANIFEST)

    issues = libimagesmanifest.check_images_manifest_format(
        images_path,
        libimagesmanifest.ManifestCheckContext(
            "4.8.5",
            "4.9.0",
            ECK_STACK_DEPS,
            eck_stack_values("8.19.19"),
            eck_stack_values("8.19.3"),
            chart_dir=tmp_path,
        ),
    )

    assert not any("has no preceding comment" in i for i in issues)
    assert not any("did not change" in i for i in issues)
    assert not any("has no entry" in i for i in issues)


def test_images_manifest_format_correctly_ordered_entries_are_not_flagged(
    libimagesmanifest: ModuleType, tmp_path: Path
):
    deps = [
        {"name": "redis-operator", "version": "1.0.0"},
        {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.0"},
    ]
    values = {
        "redis-operator": {"image": {"repository": "quay.io/opstree/redis-operator", "tag": "0.26.0@sha256:aaaa"}},
        "zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "5.4.4@sha256:bbbb"}},
    }
    (tmp_path / "Chart.yaml").write_text(yaml.safe_dump({"dependencies": deps}, sort_keys=False), encoding="utf-8")
    (tmp_path / "values.yaml").write_text(yaml.safe_dump(values, sort_keys=False), encoding="utf-8")
    images_path = tmp_path / "images-4.9.0.yaml"
    images_path.write_text(
        "# Baseline: podiumd 4.8.5.\n#\n# podiumd 4.9.0 vs 4.8.5.\n\n"
        "# redis-operator 0.25.0 -> 0.26.0\n"
        "- name: opstree/redis-operator\n"
        "  url: quay.io/opstree/redis-operator\n"
        '  version: "0.26.0"\n'
        '  digest: "sha256:aaaa"\n\n'
        "# zac 5.0.2 -> 5.4.4\n"
        "- name: infonl/zaakafhandelcomponent\n"
        "  url: ghcr.io/infonl/zaakafhandelcomponent\n"
        '  version: "5.4.4"\n'
        '  digest: "sha256:bbbb"\n'
    )

    issues = libimagesmanifest.check_images_manifest_format(
        images_path,
        libimagesmanifest.ManifestCheckContext(
            "4.8.5",
            "4.9.0",
            deps,
            values,
            {},
            chart_dir=tmp_path,
        ),
    )

    assert not any("is listed right after" in i for i in issues)


def test_images_manifest_format_changes_list_correct_order_is_not_flagged(
    libimagesmanifest: ModuleType, tmp_path: Path
):
    deps = [
        {"name": "redis-operator", "version": "1.0.0"},
        {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.0"},
    ]
    values = {
        "redis-operator": {"image": {"repository": "quay.io/opstree/redis-operator", "tag": "0.26.0@sha256:aaaa"}},
        "zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "5.4.4@sha256:bbbb"}},
    }
    (tmp_path / "Chart.yaml").write_text(yaml.safe_dump({"dependencies": deps}, sort_keys=False), encoding="utf-8")
    (tmp_path / "values.yaml").write_text(yaml.safe_dump(values, sort_keys=False), encoding="utf-8")
    images_path = tmp_path / "images-4.9.0.yaml"
    images_path.write_text(
        "# Baseline: podiumd 4.8.5.\n#\n# podiumd 4.9.0 vs 4.8.5.\n#\n"
        "# Changes:\n"
        "#   1. redis-operator 0.25.0 -> 0.26.0.\n"
        "#   2. zac 5.0.2 -> 5.4.4.\n\n"
        "# redis-operator 0.25.0 -> 0.26.0\n"
        "- name: opstree/redis-operator\n"
        "  url: quay.io/opstree/redis-operator\n"
        '  version: "0.26.0"\n'
        '  digest: "sha256:aaaa"\n\n'
        "# zac 5.0.2 -> 5.4.4\n"
        "- name: infonl/zaakafhandelcomponent\n"
        "  url: ghcr.io/infonl/zaakafhandelcomponent\n"
        '  version: "5.4.4"\n'
        '  digest: "sha256:bbbb"\n'
    )

    issues = libimagesmanifest.check_images_manifest_format(
        images_path,
        libimagesmanifest.ManifestCheckContext(
            "4.8.5",
            "4.9.0",
            deps,
            values,
            {},
            chart_dir=tmp_path,
        ),
    )

    assert not any('"# Changes:" list has' in i for i in issues)


def test_images_manifest_format_entry_with_no_changes_mention_is_flagged(libimagesmanifest: ModuleType, tmp_path: Path):
    """An entry never mentioned in "# Changes:" is flagged; list-diff's missing_paths
    only catches a changed image with no entry."""
    deps = [
        {"name": "redis-operator", "version": "1.0.0"},
        {"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.0"},
    ]
    values = {
        "redis-operator": {"image": {"repository": "quay.io/opstree/redis-operator", "tag": "0.26.0@sha256:aaaa"}},
        "zac": {"image": {"repository": "ghcr.io/infonl/zaakafhandelcomponent", "tag": "5.4.4@sha256:bbbb"}},
    }
    (tmp_path / "Chart.yaml").write_text(yaml.safe_dump({"dependencies": deps}, sort_keys=False), encoding="utf-8")
    (tmp_path / "values.yaml").write_text(yaml.safe_dump(values, sort_keys=False), encoding="utf-8")
    images_path = tmp_path / "images-4.9.0.yaml"
    images_path.write_text(
        "# Baseline: podiumd 4.8.5.\n#\n# podiumd 4.9.0 vs 4.8.5.\n#\n"
        "# Changes:\n"
        "#   1. redis-operator 0.25.0 -> 0.26.0.\n\n"
        "# redis-operator 0.25.0 -> 0.26.0\n"
        "- name: opstree/redis-operator\n"
        "  url: quay.io/opstree/redis-operator\n"
        '  version: "0.26.0"\n'
        '  digest: "sha256:aaaa"\n\n'
        "# zac 5.0.2 -> 5.4.4\n"
        "- name: infonl/zaakafhandelcomponent\n"
        "  url: ghcr.io/infonl/zaakafhandelcomponent\n"
        '  version: "5.4.4"\n'
        '  digest: "sha256:bbbb"\n'
    )

    issues = libimagesmanifest.check_images_manifest_format(
        images_path,
        libimagesmanifest.ManifestCheckContext(
            "4.8.5",
            "4.9.0",
            deps,
            values,
            {},
            chart_dir=tmp_path,
        ),
    )

    assert any('image "zac" has an entry but no mention in the "# Changes:" list' in i for i in issues)


def test_images_manifest_format_free_form_mention_still_counts_as_covered(
    libimagesmanifest: ModuleType, tmp_path: Path
):
    """A free-form item matching only via match_changes_item_to_entry's basename match
    (e.g. "redis-ha" for "redis-operator - redis") still covers the entry."""
    deps = [{"name": "redis-operator", "version": "1.0.0"}]
    values = {
        "redis-operator": {"redis-ha": {"image": {"repository": "quay.io/opstree/redis", "tag": "8.6.6@sha256:aaaa"}}}
    }
    (tmp_path / "Chart.yaml").write_text(yaml.safe_dump({"dependencies": deps}, sort_keys=False), encoding="utf-8")
    (tmp_path / "values.yaml").write_text(yaml.safe_dump(values, sort_keys=False), encoding="utf-8")
    images_path = tmp_path / "images-4.9.0.yaml"
    images_path.write_text(
        "# Baseline: podiumd 4.8.5.\n#\n# podiumd 4.9.0 vs 4.8.5.\n#\n"
        "# Changes:\n"
        "#   1. redis-ha 8.6.2 -> 8.6.6\n"
        "#   2. some other free-form item -> nothing to do with this\n\n"
        "#   sidecar: redis-operator - redis 8.6.2 -> 8.6.6\n"
        "- name: opstree/redis\n"
        "  url: quay.io/opstree/redis\n"
        '  version: "8.6.6"\n'
        '  digest: "sha256:aaaa"\n'
    )

    issues = libimagesmanifest.check_images_manifest_format(
        images_path,
        libimagesmanifest.ManifestCheckContext(
            "4.8.5",
            "4.9.0",
            deps,
            values,
            {},
            chart_dir=tmp_path,
        ),
    )

    assert not any("no mention in the" in i for i in issues)


def test_images_manifest_format_one_item_covers_every_entry_in_a_lockstep_group(
    libimagesmanifest: ModuleType, tmp_path: Path
):
    """One Changes item naming a lockstep group's shared display name covers both entries;
    compare by display name, not position."""
    deps = [{"name": "zgw-office-addin", "version": "0.0.89"}]
    values = {
        "zgw-office-addin": {
            "frontend": {"image": {"repository": "infonl/zgw-office-addin-frontend", "tag": "0.11.0@sha256:aaaa"}},
            "backend": {"image": {"repository": "infonl/zgw-office-addin-backend", "tag": "0.11.0@sha256:bbbb"}},
        }
    }
    (tmp_path / "Chart.yaml").write_text(yaml.safe_dump({"dependencies": deps}, sort_keys=False), encoding="utf-8")
    (tmp_path / "values.yaml").write_text(yaml.safe_dump(values, sort_keys=False), encoding="utf-8")
    images_path = tmp_path / "images-4.9.0.yaml"
    images_path.write_text(
        "# Baseline: podiumd 4.8.5.\n#\n# podiumd 4.9.0 vs 4.8.5.\n#\n"
        "# Changes:\n"
        "#   1. zgw-office-addin 0.9.313 -> 0.11.0.\n\n"
        "# zgw-office-addin 0.9.313 -> 0.11.0\n"
        "- name: infonl/zgw-office-addin-frontend\n"
        "  url: infonl/zgw-office-addin-frontend\n"
        '  version: "0.11.0"\n'
        '  digest: "sha256:aaaa"\n'
        "- name: infonl/zgw-office-addin-backend\n"
        "  url: infonl/zgw-office-addin-backend\n"
        '  version: "0.11.0"\n'
        '  digest: "sha256:bbbb"\n'
    )

    issues = libimagesmanifest.check_images_manifest_format(
        images_path,
        libimagesmanifest.ManifestCheckContext(
            "4.8.5",
            "4.9.0",
            deps,
            values,
            {},
            chart_dir=tmp_path,
        ),
    )

    assert not any("no mention in the" in i for i in issues)


# --- Changes items for plain images with no Chart.yaml dependency (e.g. init-container):
# fall back to this manifest's entries instead of flagging a missing dependency ---

PYTHON_MANIFEST = """\
# Baseline: podiumd 4.8.5 (origin/feature/podiumd-4.8.5 @ f27a008).
#
# Images new or changed in podiumd 4.9.0 vs 4.8.5.
#
# Changes:
#   1. Python (ensurePodiumdAdminUser init image) 3.14-slim -> 3.14.7-slim —
#      now pinned to a specific patch instead of the floating minor tag.
#
# See docs/_UPGRADE_PATHS/4.8.5-to-4.9.0-upgrade.md for the operator upgrade notes.

# Python (ensurePodiumdAdminUser init image) — 3.14-slim -> 3.14.7-slim
- name: library/python
  url: docker.io/library/python
  version: "3.14.7-slim"
  digest: "sha256:ccc"
"""


def test_images_manifest_format_plain_image_changes_item_matches_entry(libimagesmanifest: ModuleType, tmp_path: Path):
    """A plain-image Changes item resolves against the manifest's "library/python" entry
    and passes when target versions agree."""
    images_path = tmp_path / "images-4.9.0.yaml"
    images_path.write_text(PYTHON_MANIFEST)
    issues = libimagesmanifest.check_images_manifest_format(
        images_path,
        libimagesmanifest.ManifestCheckContext(
            "4.8.5",
            "4.9.0",
            DEPS,
            VALUES,
            {},
        ),
    )
    assert issues == []


def test_images_manifest_format_plain_image_changes_item_target_mismatch(libimagesmanifest: ModuleType, tmp_path: Path):
    """Once resolved to its entry, a real mismatch must still be caught."""
    text = PYTHON_MANIFEST.replace("3.14-slim -> 3.14.7-slim —", "3.14-slim -> 9.9.9 —")
    images_path = tmp_path / "images-4.9.0.yaml"
    images_path.write_text(text)
    issues = libimagesmanifest.check_images_manifest_format(
        images_path,
        libimagesmanifest.ManifestCheckContext(
            "4.8.5",
            "4.9.0",
            DEPS,
            VALUES,
            {},
        ),
    )
    assert any("target app" in i and "9.9.9" in i for i in issues)


def test_images_manifest_format_changes_item_matching_neither_dep_nor_entry_still_reported(
    libimagesmanifest: ModuleType, tmp_path: Path
):
    text = PYTHON_MANIFEST.replace("Python (ensurePodiumdAdminUser init image)", "Totally Unknown Thing")
    images_path = tmp_path / "images-4.9.0.yaml"
    images_path.write_text(text)
    issues = libimagesmanifest.check_images_manifest_format(
        images_path,
        libimagesmanifest.ManifestCheckContext(
            "4.8.5",
            "4.9.0",
            DEPS,
            VALUES,
            {},
        ),
    )
    assert any(
        'Totally Unknown Thing" — no matching Chart.yaml dependency or images-manifest entry' in i for i in issues
    )


def test_images_manifest_format_changes_item_resolves_via_canonical_path_segment_name(
    libimagesmanifest: ModuleType, tmp_path: Path
):
    """Regression: a canonical sidecar item whose basename is a values-path segment (e.g.
    "redis-operator - controller") must resolve via its known path; no entry is named
    "controller", so basename word-matching always fails."""
    deps = [{"name": "redis-operator", "version": "0.27.0"}]
    values = {
        "redis-operator": {"controller": {"image": {"repository": "quay.io/opstree/redis-operator", "tag": "0.27.0"}}}
    }
    (tmp_path / "Chart.yaml").write_text(yaml.safe_dump({"dependencies": deps}, sort_keys=False), encoding="utf-8")
    (tmp_path / "values.yaml").write_text(yaml.safe_dump(values, sort_keys=False), encoding="utf-8")
    images_path = tmp_path / "images-4.9.0.yaml"
    images_path.write_text(
        "# Baseline: podiumd 4.8.5.\n#\n# podiumd 4.9.0 vs 4.8.5.\n\n"
        "# Changes:\n"
        "#   1. redis-operator - controller 0.26.1 -> 0.27.0.\n"
        "#\n\n"
        "#   sidecar: redis-operator - controller 0.26.1 -> 0.27.0\n"
        "- name: opstree/redis-operator\n"
        "  url: opstree/redis-operator\n"
        '  version: "0.27.0"\n'
        '  digest: "sha256:eee"\n'
    )

    issues = libimagesmanifest.check_images_manifest_format(
        images_path,
        libimagesmanifest.ManifestCheckContext(
            "4.8.5",
            "4.9.0",
            deps,
            values,
            {},
            chart_dir=tmp_path,
        ),
    )

    assert not any("no matching" in i for i in issues), issues


def test_images_manifest_format_changes_item_canonical_path_segment_target_mismatch(
    libimagesmanifest: ModuleType, tmp_path: Path
):
    """A real target-version mismatch is still caught after path-segment resolution."""
    deps = [{"name": "redis-operator", "version": "0.27.0"}]
    values = {
        "redis-operator": {"controller": {"image": {"repository": "quay.io/opstree/redis-operator", "tag": "0.27.0"}}}
    }
    (tmp_path / "Chart.yaml").write_text(yaml.safe_dump({"dependencies": deps}, sort_keys=False), encoding="utf-8")
    (tmp_path / "values.yaml").write_text(yaml.safe_dump(values, sort_keys=False), encoding="utf-8")
    images_path = tmp_path / "images-4.9.0.yaml"
    images_path.write_text(
        "# Baseline: podiumd 4.8.5.\n#\n# podiumd 4.9.0 vs 4.8.5.\n\n"
        "# Changes:\n"
        "#   1. redis-operator - controller 0.26.1 -> 9.9.9.\n"
        "#\n\n"
        "#   sidecar: redis-operator - controller 0.26.1 -> 9.9.9\n"
        "- name: opstree/redis-operator\n"
        "  url: opstree/redis-operator\n"
        '  version: "0.27.0"\n'
        '  digest: "sha256:eee"\n'
    )

    issues = libimagesmanifest.check_images_manifest_format(
        images_path,
        libimagesmanifest.ManifestCheckContext(
            "4.8.5",
            "4.9.0",
            deps,
            values,
            {},
            chart_dir=tmp_path,
        ),
    )

    assert any("target app" in i and "9.9.9" in i for i in issues), issues


# --- exact-vs-fuzzy Changes item collision: "Kiss's ECK-managed ..." fuzzy-matches
# "kiss" while an exact "KISS ..." item already claims it ---

KISS_MANIFEST = """\
# Baseline: podiumd 4.8.5 (origin/feature/podiumd-4.8.5 @ f27a008).
#
# Images new or changed in podiumd 4.9.0 vs 4.8.5.
#
# Changes:
#   1. Kiss's ECK-managed Elasticsearch/Kibana/Enterprise Search 8.19.3 -> 8.19.19
#      (16-patch bump on the same 8.19.x branch, all three components in lockstep).
#   2. KISS 2.2.4 -> 3.0.0.
#
# See docs/_UPGRADE_PATHS/4.8.5-to-4.9.0-upgrade.md for the operator upgrade notes.

[]
"""

KISS_DEPS = [make_dep("kiss-chart", "3.0.0", alias="kiss")]
KISS_VALUES = {"kiss": {"image": {"tag": "3.0.0@sha256:bbb"}}}


def test_images_manifest_format_exact_item_wins_over_fuzzy_changes_item(libimagesmanifest: ModuleType, tmp_path: Path):
    """Regression: the fuzzy "Kiss's ECK-managed ..." item was compared against kiss's
    app version (bogus mismatch); it must be reported as wrong/stale, the exact item pass."""
    images_path = tmp_path / "images-4.9.0.yaml"
    images_path.write_text(KISS_MANIFEST)
    issues = libimagesmanifest.check_images_manifest_format(
        images_path,
        libimagesmanifest.ManifestCheckContext(
            "4.8.5",
            "4.9.0",
            KISS_DEPS,
            KISS_VALUES,
            {},
        ),
    )
    assert any(
        'Changes item "Kiss\'s ECK-managed Elasticsearch/Kibana/Enterprise Search" is wrong or stale '
        "— not found in Chart.yaml or values.yaml" in i
        for i in issues
    )
    assert not any("8.19.19" in i for i in issues)
    assert not any(i.startswith('images-4.9.0.yaml: Changes item "KISS"') for i in issues)


# --- historical images-<version>.yaml fallback for a new component absent from baseline ---

NEW_DEP_DEPS = [*DEPS, make_dep("brp-personen-mock", "1.2.9", alias="brppersonenmock")]
NEW_DEP_VALUES = dict(
    VALUES, brppersonenmock={"image": {"repository": "ghcr.io/brp-api/personen-mock", "tag": "2.7.0@sha256:bbbb"}}
)


def test_images_manifest_format_new_component_image_already_in_historical_manifest(
    libimagesmanifest: ModuleType, tmp_path: Path
):
    """A new dependency (no baseline key) whose exact version+digest is in an earlier
    docs/images/images-4.8.0.yaml must not be flagged as missing an entry."""
    (tmp_path / "docs" / "images").mkdir(parents=True)
    (tmp_path / "Chart.yaml").write_text(yaml.safe_dump({"dependencies": NEW_DEP_DEPS}), encoding="utf-8")
    (tmp_path / "values.yaml").write_text(yaml.safe_dump(NEW_DEP_VALUES), encoding="utf-8")
    (tmp_path / "docs" / "images" / "images-4.8.0.yaml").write_text(
        "- name: brp-api/personen-mock\n"
        "  url: ghcr.io/brp-api/personen-mock\n"
        '  version: "2.7.0"\n'
        '  digest: "sha256:bbbb"\n',
        encoding="utf-8",
    )
    images_path = tmp_path / "docs" / "images" / "images-4.9.0.yaml"
    images_path.write_text(REAL_MANIFEST)
    issues = libimagesmanifest.check_images_manifest_format(
        images_path,
        libimagesmanifest.ManifestCheckContext(
            "4.8.5",
            "4.9.0",
            NEW_DEP_DEPS,
            NEW_DEP_VALUES,
            VALUES,
            chart_dir=tmp_path,
        ),
    )
    assert not any("brp-api/personen-mock" in i or "brppersonenmock" in i for i in issues)


def test_images_manifest_format_new_component_image_not_in_historical_manifest(
    libimagesmanifest: ModuleType, tmp_path: Path
):
    """No historical manifest records the repository: flagged as missing."""
    (tmp_path / "docs" / "images").mkdir(parents=True)
    (tmp_path / "Chart.yaml").write_text(yaml.safe_dump({"dependencies": NEW_DEP_DEPS}), encoding="utf-8")
    (tmp_path / "values.yaml").write_text(yaml.safe_dump(NEW_DEP_VALUES), encoding="utf-8")
    (tmp_path / "docs" / "images" / "images-4.8.0.yaml").write_text(
        '- name: some-other/image\n  url: ghcr.io/some-other/image\n  version: "1.0.0"\n  digest: "sha256:cccc"\n',
        encoding="utf-8",
    )
    images_path = tmp_path / "docs" / "images" / "images-4.9.0.yaml"
    images_path.write_text(REAL_MANIFEST)
    issues = libimagesmanifest.check_images_manifest_format(
        images_path,
        libimagesmanifest.ManifestCheckContext(
            "4.8.5",
            "4.9.0",
            NEW_DEP_DEPS,
            NEW_DEP_VALUES,
            VALUES,
            chart_dir=tmp_path,
        ),
    )
    assert any('image "brppersonenmock" changed vs 4.8.5 but has no entry' in i for i in issues)


def test_images_manifest_format_reports_an_entry_count_mismatch(libimagesmanifest: ModuleType, tmp_path: Path):
    """An entry whose "name:" is not its first key is valid YAML but not
    matched by "^-\\s*name:", so entries and comments can not be paired:
    one issue, never a zip(strict=True) crash."""
    text = REAL_MANIFEST.replace(
        "- name: openpolicyagent/opa\n  url: openpolicyagent/opa\n",
        "- url: openpolicyagent/opa\n  name: openpolicyagent/opa\n",
    )
    images_path = tmp_path / "images-4.9.0.yaml"
    images_path.write_text(text)

    issues = libimagesmanifest.check_images_manifest_format(
        images_path, libimagesmanifest.ManifestCheckContext("4.8.5", "4.9.0", DEPS, VALUES, {})
    )

    assert any("found 2 manifest entries but 1 lines matched" in i for i in issues)


def test_images_manifest_format_reports_a_legacy_name_that_still_resolves(
    libimagesmanifest: ModuleType, tmp_path: Path
):
    """ "zac" still resolves to its values-tree path, but is not its url
    minus the registry host, so the ACR mirror would use the wrong name."""
    text = REAL_MANIFEST.replace("- name: infonl/zaakafhandelcomponent\n", "- name: zac\n")
    images_path = tmp_path / "images-4.9.0.yaml"
    images_path.write_text(text)

    issues = libimagesmanifest.check_images_manifest_format(
        images_path, libimagesmanifest.ManifestCheckContext("4.8.5", "4.9.0", DEPS, VALUES, {})
    )

    assert issues == [
        'images-4.9.0.yaml: entry "zac" should be named "infonl/zaakafhandelcomponent" (its url minus the registry host)'
    ]
