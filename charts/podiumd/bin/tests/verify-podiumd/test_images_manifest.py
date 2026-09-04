"""parse_changes_block, check_images_manifest_format — including the two
regressions found during development: a version number like "1.17.1-static"
on a continuation line being mistaken for a new numbered list item, and a
trailing period being captured as part of a version."""
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
- name: zac
  url: ghcr.io/infonl/zaakafhandelcomponent
  version: "5.4.3"
  digest: "sha256:aaa"

# ZAC OPA sidecar — 1.17.1-static -> 1.19.0-static
- name: opa
  url: openpolicyagent/opa
  version: "1.19.0-static"
  digest: "sha256:bbb"
"""


def test_parse_changes_block_extracts_all_items(libupgradedoc):
    items = libupgradedoc.parse_changes_block(REAL_MANIFEST)
    assert len(items) == 2
    assert items[0]["name"] == "ZAC (Zaakafhandelcomponent)"
    assert items[0]["app_source"] == "5.0.2"
    assert items[0]["app"] == "5.4.3"
    assert items[0]["chart_source"] == "1.0.297"
    assert items[0]["chart"] == "1.0.297"
    assert items[1]["name"] == "ZGW Office Add-in"
    assert items[1]["app_source"] == "v0.9.313"
    assert items[1]["app"] == "0.11.0"


def test_parse_changes_block_does_not_mistake_version_continuation_for_new_item(libupgradedoc):
    """Regression: "1.17.1-static -> 1.19.0-static" on an indented
    continuation line must not be parsed as a bogus item #17."""
    items = libupgradedoc.parse_changes_block(REAL_MANIFEST)
    names = [i["name"] for i in items]
    assert not any("17.1" in n for n in names)


def test_parse_changes_block_no_changes_section(libupgradedoc):
    assert libupgradedoc.parse_changes_block("# just a header\n# no changes block\n") == []


# --- check_images_manifest_format ---

DEPS = [
    make_dep("zaakafhandelcomponent", "1.0.297", alias="zac"),
    make_dep("zgw-office-addin", "0.0.92"),
]
VALUES = {"zac": {"image": {"tag": "5.4.3@sha256:aaa"}, "opa": {"image": {"tag": "1.19.0-static@sha256:bbb"}}}}


def test_images_manifest_format_passes_for_consistent_manifest(libdocsconsistency, tmp_path):
    images_path = tmp_path / "images-4.9.0.yaml"
    images_path.write_text(REAL_MANIFEST)
    issues = libdocsconsistency.check_images_manifest_format(images_path, "4.8.5", "4.9.0", DEPS, VALUES, {})
    assert issues == []


def test_images_manifest_format_missing_file(libdocsconsistency, tmp_path):
    issues = libdocsconsistency.check_images_manifest_format(tmp_path / "missing.yaml", "4.8.5", "4.9.0", DEPS, VALUES, {})
    assert "does not exist" in issues[0]


def test_images_manifest_format_invalid_yaml(libdocsconsistency, tmp_path):
    images_path = tmp_path / "images-4.9.0.yaml"
    images_path.write_text("- name: zac\n  bad: [\n")
    issues = libdocsconsistency.check_images_manifest_format(images_path, "4.8.5", "4.9.0", DEPS, VALUES, {})
    assert any("not valid YAML" in i for i in issues)


def test_images_manifest_format_missing_required_keys(libdocsconsistency, tmp_path):
    images_path = tmp_path / "images-4.9.0.yaml"
    images_path.write_text("- name: zac\n  version: \"5.4.3\"\n")
    issues = libdocsconsistency.check_images_manifest_format(images_path, "4.8.5", "4.9.0", DEPS, VALUES, {})
    assert any("missing key" in i for i in issues)


def test_images_manifest_format_stale_baseline_header(libdocsconsistency, tmp_path):
    text = REAL_MANIFEST.replace("podiumd 4.8.5", "podiumd 4.8.2").replace(
        "4.9.0 vs 4.8.5", "4.9.0 vs 4.8.2")
    images_path = tmp_path / "images-4.9.0.yaml"
    images_path.write_text(text)
    issues = libdocsconsistency.check_images_manifest_format(images_path, "4.8.5", "4.9.0", DEPS, VALUES, {})
    assert any('baseline line says "4.8.2"' in i for i in issues)
    assert any('"... vs ..." line says upgrade_docs_baseline "4.8.2"' in i for i in issues)


def test_images_manifest_format_trailing_period_not_captured(libdocsconsistency, tmp_path):
    """Regression: the "vs" line ends with a bare period right after the
    baseline number ("vs 4.8.5."); it must not be captured as part of the
    version string."""
    images_path = tmp_path / "images-4.9.0.yaml"
    images_path.write_text(REAL_MANIFEST)
    issues = libdocsconsistency.check_images_manifest_format(images_path, "4.8.5", "4.9.0", DEPS, VALUES, {})
    assert not any("4.8.5." in i for i in issues)


def test_images_manifest_format_baseline_line_trailing_period_not_captured(libdocsconsistency, tmp_path):
    """Regression: component_docs.IMAGES_STUB_TEMPLATE writes the baseline
    line as "# Baseline: podiumd 4.9.0. Re-verify before release." — a
    period directly after the version. "." is inside the capture class, so
    without .rstrip(".") every freshly-scaffolded manifest fails the format
    precheck with 'baseline line says "4.9.0."'."""
    text = REAL_MANIFEST.replace(
        "# Baseline: podiumd 4.8.5 (origin/feature/podiumd-4.8.5 @ f27a008).",
        "# Baseline: podiumd 4.8.5. Re-verify before release.",
    )
    images_path = tmp_path / "images-4.9.0.yaml"
    images_path.write_text(text)
    issues = libdocsconsistency.check_images_manifest_format(images_path, "4.8.5", "4.9.0", DEPS, VALUES, {})
    assert not any("4.8.5." in i for i in issues)
    assert not any("baseline line says" in i for i in issues)


def test_images_manifest_format_changes_block_target_mismatch(libdocsconsistency, tmp_path):
    text = REAL_MANIFEST.replace("5.0.2 -> 5.4.3 (chart 1.0.297", "5.0.2 -> 5.9.9 (chart 1.0.297")
    images_path = tmp_path / "images-4.9.0.yaml"
    images_path.write_text(text)
    issues = libdocsconsistency.check_images_manifest_format(images_path, "4.8.5", "4.9.0", DEPS, VALUES, {})
    assert any("target app" in i and "5.9.9" in i for i in issues)


def test_images_manifest_format_entry_comment_target_mismatch(libdocsconsistency, tmp_path):
    text = REAL_MANIFEST.replace(
        "# ZAC OPA sidecar — 1.17.1-static -> 1.19.0-static",
        "# ZAC OPA sidecar — 1.17.1-static -> 9.9.9-static",
    )
    images_path = tmp_path / "images-4.9.0.yaml"
    images_path.write_text(text)
    issues = libdocsconsistency.check_images_manifest_format(images_path, "4.8.5", "4.9.0", DEPS, VALUES, {})
    assert any('comment says target "9.9.9-static"' in i for i in issues)


def test_images_manifest_format_missing_entry_comment(libdocsconsistency, tmp_path):
    text = REAL_MANIFEST.replace("# ZAC OPA sidecar — 1.17.1-static -> 1.19.0-static\n", "")
    images_path = tmp_path / "images-4.9.0.yaml"
    images_path.write_text(text)
    issues = libdocsconsistency.check_images_manifest_format(images_path, "4.8.5", "4.9.0", DEPS, VALUES, {})
    assert any('entry "opa" has no preceding comment' in i for i in issues)


ZGW_MANIFEST = """\
# Baseline: podiumd 4.8.5 (origin/feature/podiumd-4.8.5 @ f27a008).
#
# Images new or changed in podiumd 4.9.0 vs 4.8.5.
#
# Changes:
#   1. ZGW Office Add-in v0.9.313 -> v0.9.352 (chart 0.0.89, unchanged).

# ZGW Office Add-in — v0.9.313 -> v0.9.352
- name: zgw-office-addin-frontend
  url: ghcr.io/infonl/zgw-office-addin-frontend
  version: "v0.9.352"
  digest: "sha256:aaa"

- name: zgw-office-addin-backend
  url: ghcr.io/infonl/zgw-office-addin-backend
  version: "v0.9.352"
  digest: "sha256:bbb"
"""
ZGW_DEPS = [make_dep("zgw-office-addin", "0.0.89")]
ZGW_VALUES = {"zgw-office-addin": {
    "frontend": {"image": {"tag": "v0.9.352@sha256:aaa"}},
    "backend": {"image": {"tag": "v0.9.352@sha256:bbb"}},
}}


def test_images_manifest_format_multi_image_component_shares_one_comment(libdocsconsistency, tmp_path):
    """A multi-image component (zgw-office-addin's frontend + backend) needs
    only ONE preceding comment for the whole group — the second entry, with
    a blank line (not a comment) directly above it, must NOT be flagged as
    missing a comment of its own."""
    images_path = tmp_path / "images-4.9.0.yaml"
    images_path.write_text(ZGW_MANIFEST)
    issues = libdocsconsistency.check_images_manifest_format(images_path, "4.8.5", "4.9.0", ZGW_DEPS, ZGW_VALUES, {})
    assert issues == []


def test_images_manifest_format_source_vs_baseline(libdocsconsistency, tmp_path):
    baseline_values = {"zac": {"opa": {"image": {"tag": "1.17.1-static@sha256:old"}}}}
    images_path = tmp_path / "images-4.9.0.yaml"
    images_path.write_text(REAL_MANIFEST)
    issues = libdocsconsistency.check_images_manifest_format(images_path, "4.8.5", "4.9.0", DEPS, VALUES, baseline_values)
    assert issues == []


def test_images_manifest_format_source_vs_baseline_mismatch(libdocsconsistency, tmp_path):
    # baseline actually has a different starting version than the comment claims
    baseline_values = {"zac": {"opa": {"image": {"tag": "2.0.0-static@sha256:old"}}}}
    images_path = tmp_path / "images-4.9.0.yaml"
    images_path.write_text(REAL_MANIFEST)
    issues = libdocsconsistency.check_images_manifest_format(images_path, "4.8.5", "4.9.0", DEPS, VALUES, baseline_values)
    assert any('comment says source "1.17.1-static"' in i for i in issues)


# --- the list-diff check (chart_dir given) against a COMPONENT_VERSION_
# PATHS-registered component — real bug: redis-operator's own image is
# pinned as flat sibling scalars ("redisOperator.imageTag"/"imageName"),
# never nested under an "image:" dict at all, so it was completely
# invisible to the list-diff's structural scan — a real version bump
# was reported as "entry ... is listed but its image did not change".

REDIS_OPERATOR_DEPS = [make_dep("redis-operator", "0.26.1")]


def redis_operator_values(tag):
    # redis-ha's own sidecar image (ordinary "image: {tag: ...}" shape,
    # UNCHANGED between baseline and target here) — present so
    # find_image_tag_paths' structural scan finds SOMETHING even
    # without the fix, and the list-diff's own "if baseline_paths and
    # chart_dir is not None" guard doesn't short-circuit the whole
    # check before it ever reaches redis-operator's own entry; a
    # values.yaml with ONLY the COMPONENT_VERSION_PATHS-shaped field
    # would make current_paths/baseline_paths empty regardless of the
    # fix, silently skipping the check instead of exercising it.
    return {"redis-operator": {
        "redisOperator": {"imageName": "quay.io/opstree/redis-operator", "imageTag": f"{tag}@sha256:aaa"},
        "redis-ha": {"image": {"repository": "quay.io/opstree/redis", "tag": "8.6.6@sha256:bbb"}},
    }}


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


def test_images_manifest_format_component_version_path_change_is_recognized(libdocsconsistency, tmp_path):
    (tmp_path / "Chart.yaml").write_text(yaml.safe_dump({"dependencies": REDIS_OPERATOR_DEPS}), encoding="utf-8")
    (tmp_path / "values.yaml").write_text(yaml.safe_dump(redis_operator_values("v0.26.0")), encoding="utf-8")
    images_path = tmp_path / "images-4.9.0.yaml"
    images_path.write_text(REDIS_OPERATOR_MANIFEST)

    issues = libdocsconsistency.check_images_manifest_format(
        images_path, "4.8.5", "4.9.0", REDIS_OPERATOR_DEPS,
        redis_operator_values("v0.26.0"), redis_operator_values("v0.25.0"), chart_dir=tmp_path)

    assert not any("did not change" in i for i in issues)
    assert not any("has no entry" in i for i in issues)


def make_nested_subchart_tgz(chart_dir, name, version, nested_charts):
    """A minimal vendored <name>-<version>.tgz with, for each (nested
    chart name, values.yaml raw text) pair in `nested_charts`, a
    "<name>/charts/<nested>/values.yaml" member — enough to exercise
    nested_subchart_documented_image_repository without a real
    `helm pull`."""
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
    return {"kiss-eck": {
        "eck-elasticsearch": {"version": version},
        "eck-kibana": {"version": version},
        "eck-enterprise-search": {"version": version},
    }}


def test_images_manifest_format_sidecars_recognized_within_group_by_basename(libdocsconsistency, tmp_path):
    """kibana/enterprise-search share elasticsearch's ONE group header
    (no comment of their own, same convention every other multi-entry
    group in the real manifest uses — e.g. ZGW Office Add-in's frontend
    + backend) — component_of must resolve ALL THREE via the same
    deterministic repo_map lookup the list-diff check already uses, not
    fuzzy word-matching against the group's own free-form header text,
    so none of them are wrongly flagged as having no preceding comment."""
    (tmp_path / "Chart.yaml").write_text(yaml.safe_dump({"dependencies": ECK_STACK_DEPS}), encoding="utf-8")
    (tmp_path / "values.yaml").write_text(yaml.safe_dump(eck_stack_values("8.19.19")), encoding="utf-8")
    make_nested_subchart_tgz(tmp_path, "eck-stack", "0.20.0", {
        "eck-elasticsearch": "# image: docker.elastic.co/elasticsearch/elasticsearch:9.5.0\n",
        "eck-kibana": "# image: docker.elastic.co/kibana/kibana:9.5.0\n",
        "eck-enterprise-search": "# image: docker.elastic.co/enterprise-search/enterprise-search:8.19.0\n",
    })
    images_path = tmp_path / "images-4.9.0.yaml"
    images_path.write_text(ECK_STACK_MANIFEST)

    issues = libdocsconsistency.check_images_manifest_format(
        images_path, "4.8.5", "4.9.0", ECK_STACK_DEPS,
        eck_stack_values("8.19.19"), eck_stack_values("8.19.3"), chart_dir=tmp_path)

    assert not any("has no preceding comment" in i for i in issues)
    assert not any("did not change" in i for i in issues)
    assert not any("has no entry" in i for i in issues)


def test_images_manifest_format_out_of_order_entries_are_flagged(libdocsconsistency, tmp_path):
    """Entries listed in the OPPOSITE order from values.yaml's own top-
    level component order — same "rows/Changes headings should follow
    values.yaml's own order" rule already enforced for -upgrade.md,
    reused here via images_manifest_entry_order_key."""
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
        "# zac 5.0.2 -> 5.4.4\n"
        "- name: infonl/zaakafhandelcomponent\n"
        "  url: ghcr.io/infonl/zaakafhandelcomponent\n"
        '  version: "5.4.4"\n'
        '  digest: "sha256:bbbb"\n\n'
        "# redis-operator 0.25.0 -> 0.26.0\n"
        "- name: opstree/redis-operator\n"
        "  url: quay.io/opstree/redis-operator\n"
        '  version: "0.26.0"\n'
        '  digest: "sha256:aaaa"\n'
    )

    issues = libdocsconsistency.check_images_manifest_format(
        images_path, "4.8.5", "4.9.0", deps, values, {}, chart_dir=tmp_path)

    assert any('entry "redis-operator" is listed right after "zac"' in i
                and "values.yaml lists redis-operator before zac" in i
                for i in issues)


def test_images_manifest_format_correctly_ordered_entries_are_not_flagged(libdocsconsistency, tmp_path):
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

    issues = libdocsconsistency.check_images_manifest_format(
        images_path, "4.8.5", "4.9.0", deps, values, {}, chart_dir=tmp_path)

    assert not any("is listed right after" in i for i in issues)


def test_images_manifest_format_changes_list_out_of_order_is_flagged(libdocsconsistency, tmp_path):
    """Real gap: the "# Changes:" header list can be scrambled relative
    to values.yaml's own order even while the ENTRY list below it (the
    only thing find_images_manifest_out_of_order_names checks) is
    already correctly ordered — nothing previously caught this."""
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
        "#   1. zac 5.0.2 -> 5.4.4.\n"
        "#   2. redis-operator 0.25.0 -> 0.26.0.\n\n"
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

    issues = libdocsconsistency.check_images_manifest_format(
        images_path, "4.8.5", "4.9.0", deps, values, {}, chart_dir=tmp_path)

    assert any('"# Changes:" list has "redis-operator 0.25.0 -> 0.26.0." right after '
                '"zac 5.0.2 -> 5.4.4."' in i for i in issues)


def test_images_manifest_format_changes_list_correct_order_is_not_flagged(libdocsconsistency, tmp_path):
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

    issues = libdocsconsistency.check_images_manifest_format(
        images_path, "4.8.5", "4.9.0", deps, values, {}, chart_dir=tmp_path)

    assert not any('"# Changes:" list has' in i for i in issues)


def test_images_manifest_format_entry_with_no_changes_mention_is_flagged(libdocsconsistency, tmp_path):
    """Real gap: an entry can be present and perfectly correct (right
    version/digest, own preceding comment) yet never appear anywhere in
    the "# Changes:" header list at all — find_images_manifest_list_
    diff's own missing_paths only ever catches a changed image with no
    ENTRY, never an entry with no header MENTION."""
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

    issues = libdocsconsistency.check_images_manifest_format(
        images_path, "4.8.5", "4.9.0", deps, values, {}, chart_dir=tmp_path)

    assert any('image "zac" has an entry but no mention in the "# Changes:" list' in i for i in issues)


def test_images_manifest_format_free_form_mention_still_counts_as_covered(libdocsconsistency, tmp_path):
    """A Changes item using free-form prose that only resolves to an
    entry via match_changes_item_to_entry's fuzzy basename match (never
    the entry's own canonical "<key> - <basename>" display name — real
    case: "redis-ha" for what canonical_sidecar_row_names would call
    "redis-operator - redis") still counts as covering it — this must
    NOT be flagged as a missing mention just because the exact display
    name string never appears verbatim."""
    deps = [{"name": "redis-operator", "version": "1.0.0"}]
    values = {"redis-operator": {"redis-ha": {"image": {
        "repository": "quay.io/opstree/redis", "tag": "8.6.6@sha256:aaaa"}}}}
    (tmp_path / "Chart.yaml").write_text(yaml.safe_dump({"dependencies": deps}, sort_keys=False), encoding="utf-8")
    (tmp_path / "values.yaml").write_text(yaml.safe_dump(values, sort_keys=False), encoding="utf-8")
    images_path = tmp_path / "images-4.9.0.yaml"
    images_path.write_text(
        "# Baseline: podiumd 4.8.5.\n#\n# podiumd 4.9.0 vs 4.8.5.\n#\n"
        "# Changes:\n"
        "#   1. redis-ha 8.6.2 -> 8.6.6\n"
        "#   2. some other free-form item -> nothing to do with this\n\n"
        "#   sidecar: redis-operator - redis 8.6.2 -> 8.6.6\n"
        "- name: redis-ha\n"
        "  url: quay.io/opstree/redis\n"
        '  version: "8.6.6"\n'
        '  digest: "sha256:aaaa"\n'
    )

    issues = libdocsconsistency.check_images_manifest_format(
        images_path, "4.8.5", "4.9.0", deps, values, {}, chart_dir=tmp_path)

    assert not any("no mention in the" in i for i in issues)


def test_images_manifest_format_one_item_covers_every_entry_in_a_lockstep_group(libdocsconsistency, tmp_path):
    """A multi-image "lockstep" component (zgw-office-addin's frontend +
    backend — one of COMPONENT_IMAGE_PATHS' multi-path entries) has TWO
    separate entries, each its own distinct entry_positions slot, but
    both share ONE display name — ONE Changes item naming that shared
    display name must cover BOTH entries, not just whichever one happens
    to sit at the lower position. (Comparing by raw position instead of
    display name was an earlier, wrong version of this same check.)"""
    deps = [{"name": "zgw-office-addin", "version": "0.0.89"}]
    values = {"zgw-office-addin": {
        "frontend": {"image": {"repository": "infonl/zgw-office-addin-frontend", "tag": "0.11.0@sha256:aaaa"}},
        "backend": {"image": {"repository": "infonl/zgw-office-addin-backend", "tag": "0.11.0@sha256:bbbb"}},
    }}
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

    issues = libdocsconsistency.check_images_manifest_format(
        images_path, "4.8.5", "4.9.0", deps, values, {}, chart_dir=tmp_path)

    assert not any("no mention in the" in i for i in issues)


# --- Changes items for plain images with no Chart.yaml dependency of their
# own (e.g. an init-container image) -- must fall back to this same
# manifest's own entries instead of being flagged as a missing dependency ---

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


def test_images_manifest_format_plain_image_changes_item_matches_entry(libdocsconsistency, tmp_path):
    """A Changes item for a plain image (no Chart.yaml dependency of its
    own) must not be flagged just because match_dependency finds nothing —
    it should resolve against this manifest's own "library/python" entry
    instead and pass, since the target versions agree."""
    images_path = tmp_path / "images-4.9.0.yaml"
    images_path.write_text(PYTHON_MANIFEST)
    issues = libdocsconsistency.check_images_manifest_format(images_path, "4.8.5", "4.9.0", DEPS, VALUES, {})
    assert issues == []


def test_images_manifest_format_plain_image_changes_item_target_mismatch(libdocsconsistency, tmp_path):
    """Once resolved to its entry, a real mismatch must still be caught."""
    text = PYTHON_MANIFEST.replace("3.14-slim -> 3.14.7-slim —", "3.14-slim -> 9.9.9 —")
    images_path = tmp_path / "images-4.9.0.yaml"
    images_path.write_text(text)
    issues = libdocsconsistency.check_images_manifest_format(images_path, "4.8.5", "4.9.0", DEPS, VALUES, {})
    assert any("target app" in i and "9.9.9" in i for i in issues)


def test_images_manifest_format_changes_item_matching_neither_dep_nor_entry_still_reported(
        libdocsconsistency, tmp_path):
    text = PYTHON_MANIFEST.replace(
        "Python (ensurePodiumdAdminUser init image)", "Totally Unknown Thing")
    images_path = tmp_path / "images-4.9.0.yaml"
    images_path.write_text(text)
    issues = libdocsconsistency.check_images_manifest_format(images_path, "4.8.5", "4.9.0", DEPS, VALUES, {})
    assert any('Totally Unknown Thing" — no matching Chart.yaml dependency or images-manifest entry' in i
               for i in issues)


# --- exact-vs-fuzzy Changes item collision (real-world case: "Kiss's
# ECK-managed Elasticsearch/..." fuzzy-matching the real "kiss" dependency
# even though an exact "KISS ..." item already legitimately claims it) ---

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


def test_images_manifest_format_exact_item_wins_over_fuzzy_changes_item(libdocsconsistency, tmp_path):
    """Regression test: item "Kiss's ECK-managed Elasticsearch/Kibana/
    Enterprise Search 8.19.3 -> 8.19.19" fuzzy-matches the real "kiss"
    dependency on the word "kiss" (there's also an exact "KISS 2.2.4 ->
    3.0.0" item) and used to be compared against kiss's own unrelated
    actual app version (3.0.0), producing a bogus mismatch. Now it's
    reported as wrong/stale instead, and the exact item passes cleanly."""
    images_path = tmp_path / "images-4.9.0.yaml"
    images_path.write_text(KISS_MANIFEST)
    issues = libdocsconsistency.check_images_manifest_format(
        images_path, "4.8.5", "4.9.0", KISS_DEPS, KISS_VALUES, {})
    assert any(
        'Changes item "Kiss\'s ECK-managed Elasticsearch/Kibana/Enterprise Search" is wrong or stale '
        '— not found in Chart.yaml or values.yaml' in i
        for i in issues
    )
    assert not any("8.19.19" in i for i in issues)
    assert not any(i.startswith('images-4.9.0.yaml: Changes item "KISS"') for i in issues)
