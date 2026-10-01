"""lib.upgradedoc -- preceding/grouped-comment lookup and Changes-block parsing."""

from types import ModuleType

# --- path_display_name ---


def test_path_display_name_primary_dependency_image_uses_bare_key(libupgradedoccomments: ModuleType):
    """A dependency's primary image displays as its bare values key, matching other messages."""
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.0"}]
    assert libupgradedoccomments.path_display_name(("zac", "image"), deps, canonical_names={}) == "zac"


def test_path_display_name_sidecar_uses_canonical_name(libupgradedoccomments: ModuleType):
    """A nested sidecar path displays as its canonical "<key> - <image-basename>" name."""
    deps = [{"name": "redis-operator", "version": "1.0.0"}]
    canonical_names = {"redis-operator - redis": ("redis-operator", "redis-ha", "image")}
    assert (
        libupgradedoccomments.path_display_name(("redis-operator", "redis-ha", "image"), deps, canonical_names)
        == "redis-operator - redis"
    )


def test_path_display_name_global_uses_bare_basename(libupgradedoccomments: ModuleType):
    """A shared "global" image displays as its bare basename."""
    canonical_names = {"curl": ("global", "images", "curl", "image")}
    assert (
        libupgradedoccomments.path_display_name(
            ("global", "images", "curl", "image"), deps=[], canonical_names=canonical_names
        )
        == "curl"
    )


def test_path_display_name_falls_back_to_dotted_path(libupgradedoccomments: ModuleType):
    """A path with no primary image or canonical name falls back to the dotted path, not a guess."""
    assert (
        libupgradedoccomments.path_display_name(("mystery", "nested", "image"), deps=[], canonical_names={})
        == "mystery.nested.image"
    )


def test_path_display_name_version_paths_for_field_uses_bare_key(libupgradedoccomments: ModuleType):
    """A version_paths_for bare-scalar field (redis-operator's "redisOperator.imageTag") is also the
    primary, so it displays as the bare key, as actual_app_version does."""
    deps = [{"name": "redis-operator", "version": "1.0.0"}]
    assert (
        libupgradedoccomments.path_display_name(
            ("redis-operator", "redisOperator", "imageTag"), deps, canonical_names={}
        )
        == "redis-operator"
    )


# --- find_preceding_comment ---


def test_find_preceding_comment_joins_consecutive_comment_lines(libupgradedoccomments: ModuleType):
    lines = [
        "# ZAC OPA sidecar\n",
        "# 1.17.1-static -> 1.19.0-static\n",
        "- name: opa\n",
    ]
    assert (
        libupgradedoccomments.find_preceding_comment(lines, 2) == "# ZAC OPA sidecar # 1.17.1-static -> 1.19.0-static"
    )


def test_find_preceding_comment_stops_at_blank_line(libupgradedoccomments: ModuleType):
    lines = [
        "# unrelated previous entry's comment\n",
        "\n",
        "# ZAC — 5.0.1 -> 5.1.0\n",
        "- name: zac\n",
    ]
    assert libupgradedoccomments.find_preceding_comment(lines, 3) == "# ZAC — 5.0.1 -> 5.1.0"


def test_find_preceding_comment_none_when_absent(libupgradedoccomments: ModuleType):
    lines = ["- name: zac\n"]
    assert libupgradedoccomments.find_preceding_comment(lines, 0) == ""


# --- find_grouped_preceding_comment / find_grouped_preceding_comment_line ---

ZGW_GROUPED_LINES = [
    "# ZGW Office Add-in — v0.9.313 -> v0.9.352\n",
    "- name: zgw-office-addin-frontend\n",
    '  version: "v0.9.352"\n',
    "\n",
    "- name: zgw-office-addin-backend\n",
    '  version: "v0.9.352"\n',
]
ZGW_ENTRIES = [
    {"name": "zgw-office-addin-frontend", "version": "v0.9.352"},
    {"name": "zgw-office-addin-backend", "version": "v0.9.352"},
]
ZGW_ENTRY_LINE_INDICES = [1, 4]


def component_of(entry):
    if "zgw-office-addin" in entry["name"]:
        return "zgw-office-addin"
    if entry["name"] in ("zac", "opa"):
        return "zac"
    return None


def same_group(entry_a, entry_b):
    """Grouping predicate used by check_images_manifest_format: same component and same version.

    The version check separates lockstep bumps (zgw-office-addin frontend/backend) from independently
    versioned images sharing a prefix (zac vs. zac.opa)."""
    return (
        component_of(entry_a) is not None
        and component_of(entry_a) == component_of(entry_b)
        and entry_a.get("version") == entry_b.get("version")
    )


def test_find_grouped_preceding_comment_uses_own_comment_when_present(libupgradedoccomments: ModuleType):
    comment = libupgradedoccomments.find_grouped_preceding_comment(
        ZGW_GROUPED_LINES, ZGW_ENTRIES, ZGW_ENTRY_LINE_INDICES, 0, same_group
    )
    assert comment == "# ZGW Office Add-in — v0.9.313 -> v0.9.352"


def test_find_grouped_preceding_comment_inherits_sibling_comment_across_blank_line(libupgradedoccomments: ModuleType):
    comment = libupgradedoccomments.find_grouped_preceding_comment(
        ZGW_GROUPED_LINES, ZGW_ENTRIES, ZGW_ENTRY_LINE_INDICES, 1, same_group
    )
    assert comment == "# ZGW Office Add-in — v0.9.313 -> v0.9.352"


def test_find_grouped_preceding_comment_does_not_inherit_across_different_component(libupgradedoccomments: ModuleType):
    """An entry must not inherit the preceding entry's comment across different components."""
    lines = [*ZGW_GROUPED_LINES, "\n", "- name: zac\n", '  version: "5.1.0"\n']
    entries = [*ZGW_ENTRIES, {"name": "zac", "version": "5.1.0"}]
    entry_line_indices = [*ZGW_ENTRY_LINE_INDICES, 7]

    comment = libupgradedoccomments.find_grouped_preceding_comment(lines, entries, entry_line_indices, 2, same_group)
    assert comment == ""


def test_find_grouped_preceding_comment_does_not_override_own_distinct_comment(libupgradedoccomments: ModuleType):
    """An entry's own comment wins over its group's comment."""
    lines = [
        "# ZAC — 5.0.1 -> 5.1.0\n",
        "- name: zac\n",
        '  version: "5.1.0"\n',
        "# ZAC OPA sidecar — 1.17.1-static -> 1.19.0-static\n",
        "- name: opa\n",
        '  version: "1.19.0-static"\n',
    ]
    entries = [{"name": "zac", "version": "5.1.0"}, {"name": "opa", "version": "1.19.0-static"}]
    entry_line_indices = [1, 4]

    comment = libupgradedoccomments.find_grouped_preceding_comment(lines, entries, entry_line_indices, 1, same_group)
    assert comment == "# ZAC OPA sidecar — 1.17.1-static -> 1.19.0-static"


def test_find_grouped_preceding_comment_does_not_inherit_when_versions_differ(libupgradedoccomments: ModuleType):
    """Same component but a different version is not a lockstep bump, so no comment is inherited."""
    lines = [
        "# ZAC — 5.0.1 -> 5.1.0\n",
        "- name: zac\n",
        '  version: "5.1.0"\n',
        "\n",
        "- name: opa\n",
        '  version: "1.19.0-static"\n',
    ]
    entries = [{"name": "zac", "version": "5.1.0"}, {"name": "opa", "version": "1.19.0-static"}]
    entry_line_indices = [1, 4]

    comment = libupgradedoccomments.find_grouped_preceding_comment(lines, entries, entry_line_indices, 1, same_group)
    assert comment == ""


def test_find_grouped_preceding_comment_line_uses_own_line_when_present(libupgradedoccomments: ModuleType):
    idx = libupgradedoccomments.find_grouped_preceding_comment_line(
        ZGW_GROUPED_LINES, ZGW_ENTRIES, ZGW_ENTRY_LINE_INDICES, 0, same_group
    )
    assert idx == 0


def test_find_grouped_preceding_comment_line_inherits_sibling_line_across_blank_line(libupgradedoccomments: ModuleType):
    idx = libupgradedoccomments.find_grouped_preceding_comment_line(
        ZGW_GROUPED_LINES, ZGW_ENTRIES, ZGW_ENTRY_LINE_INDICES, 1, same_group
    )
    assert idx == 0


def test_find_grouped_preceding_comment_line_none_for_different_component(libupgradedoccomments: ModuleType):
    lines = [*ZGW_GROUPED_LINES, "\n", "- name: zac\n", '  version: "5.1.0"\n']
    entries = [*ZGW_ENTRIES, {"name": "zac", "version": "5.1.0"}]
    entry_line_indices = [*ZGW_ENTRY_LINE_INDICES, 7]

    idx = libupgradedoccomments.find_grouped_preceding_comment_line(lines, entries, entry_line_indices, 2, same_group)
    assert idx is None


# --- diff_keys / flatten_leaf_keys / pair_renames ---


def test_diff_keys_finds_added_and_removed(libupgradedoccomments: ModuleType):
    baseline = {"a": 1, "b": {"x": 1}}
    current = {"a": 1, "c": {"y": 1}}
    diffs = sorted(libupgradedoccomments.diff_keys(baseline, current))
    assert ("added", ("c",)) in diffs
    assert ("removed", ("b",)) in diffs


def test_diff_keys_ignores_scalar_value_changes(libupgradedoccomments: ModuleType):
    baseline = {"a": 1}
    current = {"a": 2}
    assert list(libupgradedoccomments.diff_keys(baseline, current)) == []


def test_diff_keys_recurses_into_shared_keys(libupgradedoccomments: ModuleType):
    baseline = {"a": {"x": 1}}
    current = {"a": {"x": 1, "y": 2}}
    assert list(libupgradedoccomments.diff_keys(baseline, current)) == [("added", ("a", "y"))]


def test_flatten_leaf_keys_collects_nested_leaf_names_only(libupgradedoccomments: ModuleType):
    node = {"host": "h", "auth": {"user": "u", "password": "p"}}
    assert libupgradedoccomments.flatten_leaf_keys(node) == {"host", "user", "password"}


def test_diff_keys_yields_keys_in_sorted_order(libupgradedoccomments: ModuleType):
    """Output is sorted, so pair_renames sees the same input order in every process."""
    names = [f"key{i:02d}" for i in range(20)]
    baseline = {name: {"x": 1} for name in reversed(names[:10])} | {"shared": dict.fromkeys(reversed(names[:5]), 1)}
    current = {name: {"x": 1} for name in reversed(names[10:])} | {"shared": dict.fromkeys(reversed(names[5:10]), 1)}
    diffs = list(libupgradedoccomments.diff_keys(baseline, current))
    assert diffs == (
        [("added", (name,)) for name in names[10:]]
        + [("removed", (name,)) for name in names[:10]]
        + [("added", ("shared", name)) for name in names[5:10]]
        + [("removed", ("shared", name)) for name in names[:5]]
    )


def test_flatten_leaf_keys_excludes_intermediate_keys(libupgradedoccomments: ModuleType):
    """Dict/list-valued keys are not leaves; counting them would inflate pair_renames' similarity ratio."""
    node = {"a": {"x": 1, "y": [{"z": 2}]}}
    assert libupgradedoccomments.flatten_leaf_keys(node) == {"x", "z"}


def test_pair_renames_ignores_shared_intermediate_keys(libupgradedoccomments: ModuleType):
    """Sharing only an intermediate key ("auth") is an unrelated add and remove, not a rename."""
    baseline = {"old": {"auth": {"user": "u", "password": "p"}}}
    current = {"new": {"auth": {"token": "t"}}}
    renamed, added, removed = libupgradedoccomments.pair_renames([("new",)], [("old",)], baseline, current)
    assert renamed == []
    assert added == [("new",)]
    assert removed == [("old",)]


def test_flatten_leaf_keys_walks_lists(libupgradedoccomments: ModuleType):
    node = [{"a": 1}, {"b": 2}]
    assert libupgradedoccomments.flatten_leaf_keys(node) == {"a", "b"}


def test_pair_renames_pairs_similar_subtrees(libupgradedoccomments: ModuleType):
    baseline = {"mi": {"sftp": {"host": "h", "user": "u", "password": "p"}}}
    current = {"mi": {"transfer": {"host": "h", "user": "u", "password": "p"}}}
    added = [("mi", "transfer")]
    removed = [("mi", "sftp")]
    renamed, added_left, removed_left = libupgradedoccomments.pair_renames(added, removed, baseline, current)
    assert renamed == [(("mi", "sftp"), ("mi", "transfer"))]
    assert added_left == [] and removed_left == []


def test_pair_renames_leaves_unrelated_add_remove_alone(libupgradedoccomments: ModuleType):
    baseline = {"a": {"x": 1}}
    current = {"b": {"totally": "different", "shape": True}}
    added = [("b",)]
    removed = [("a",)]
    renamed, added_left, removed_left = libupgradedoccomments.pair_renames(added, removed, baseline, current)
    assert renamed == []
    assert added_left == [("b",)] and removed_left == [("a",)]


# --- parse_changes_block ---


def test_parse_changes_block_parses_numbered_items(libupgradedoccomments: ModuleType):
    text = (
        "# Baseline: podiumd 4.8.5.\n"
        "#\n"
        "# Changes:\n"
        "#   1. ZAC 5.0.2 -> 5.4.3 (chart 1.0.297, unchanged).\n"
        "#   2. ZGW Office Add-in v0.9.313 -> 0.11.0 (chart 0.0.89 -> 0.0.92).\n"
        "#\n"
        "# See docs/_UPGRADE_PATHS/...\n"
    )
    items = libupgradedoccomments.parse_changes_block(text)
    assert len(items) == 2
    assert items[0]["name"] == "ZAC"
    assert items[0]["app_source"] == "5.0.2"
    assert items[0]["app"] == "5.4.3"
    assert items[1]["chart_source"] == "0.0.89"
    assert items[1]["chart"] == "0.0.92"


def test_parse_changes_block_parses_items_without_a_version_pair(libupgradedoccomments: ModuleType):
    text = (
        "# Changes:\n"
        "#   1. kiss 3.1.1 (new) (chart 3.1.1, new).\n"
        "#   2. zac 5.4.4 (digest changed) (chart 1.0.297, unchanged).\n"
        "#   3. curl 8.1.0 (unchanged).\n"
    )
    items = libupgradedoccomments.parse_changes_block(text)
    assert [(i["name"], i["app_source"], i["app"]) for i in items] == [
        ("kiss", None, "3.1.1"),
        ("zac", "5.4.4", "5.4.4"),
        ("curl", "8.1.0", "8.1.0"),
    ]


def test_parse_changes_block_no_header_returns_empty(libupgradedoccomments: ModuleType):
    assert libupgradedoccomments.parse_changes_block("# just a header\n# no changes block\n") == []


def test_parse_changes_block_version_with_dot_not_mistaken_for_new_item(libupgradedoccomments: ModuleType):
    text = "# Changes:\n#   1. OPA 1.17.1-static -> 1.19.0-static\n#   2. ZAC 5.0.2 -> 5.4.3\n"
    items = libupgradedoccomments.parse_changes_block(text)
    assert len(items) == 2
    assert items[0]["app"] == "1.19.0-static"
    assert items[1]["app"] == "5.4.3"


def test_parse_changes_block_joins_a_wrapped_version_pair(libupgradedoccomments: ModuleType):
    """Regression: a version pair on a wrapped continuation line is joined; otherwise the item's
    leading word was taken as a fake version."""
    text = (
        "# Changes:\n"
        "#   21. nginx-unprivileged (shared global.images.nginx anchor, used by every\n"
        "#      nginx sidecar in the chart) 1.31.3 -> 1.31.4.\n"
        "#\n"
        "# See docs/_UPGRADE_PATHS/...\n"
    )
    items = libupgradedoccomments.parse_changes_block(text)
    assert len(items) == 1
    assert items[0]["name"] == (
        "nginx-unprivileged (shared global.images.nginx anchor, used by every nginx sidecar in the chart)"
    )
    assert items[0]["app_source"] == "1.31.3"
    assert items[0]["app"] == "1.31.4"  # not "1.31.4." — trailing sentence period stripped


def test_parse_changes_block_joins_a_wrapped_chart_version(libupgradedoccomments: ModuleType):
    """A "(chart ...)" span closing on a wrapped line is parsed, so the chart comparison is not skipped."""
    text = (
        "# Changes:\n"
        "#   1. ZAC 5.0.2 -> 5.4.4 (chart 1.0.297, unchanged — the chart line was\n"
        "#      already bumped ahead of the image in the 4.8.5 hop).\n"
    )
    items = libupgradedoccomments.parse_changes_block(text)
    assert len(items) == 1
    assert items[0]["chart_source"] == "1.0.297"
    assert items[0]["chart"] == "1.0.297"


def test_parse_changes_block_chart_only_item_with_no_parens_has_no_fake_app_version(libupgradedoccomments: ModuleType):
    """Regression: a bare "chart <source> -> <target>" clause is not taken as the app version (it
    caused a bogus mismatch for eck-stack)."""
    text = "# Changes:\n#   6. ECK Stack (kiss-eck) chart 0.19.0 -> 0.20.0 (no image change of\n#      its own).\n"
    items = libupgradedoccomments.parse_changes_block(text)
    assert len(items) == 1
    assert items[0]["chart_source"] == "0.19.0"
    assert items[0]["chart"] == "0.20.0"
    assert items[0]["app_source"] is None
    assert items[0]["app"] is None


def test_parse_changes_block_chart_pair_before_app_pair_both_extracted_correctly(libupgradedoccomments: ModuleType):
    """Chart clause before the app pair (redis-operator): each pair lands in the right field."""
    text = (
        "# Changes:\n"
        "#   15. redis-operator chart 0.25.0 -> 0.26.1, operator image 0.25.0 ->\n"
        "#      0.26.0 (quay.io/opstree/redis-operator, digest-pinned).\n"
    )
    items = libupgradedoccomments.parse_changes_block(text)
    assert len(items) == 1
    assert items[0]["chart_source"] == "0.25.0"
    assert items[0]["chart"] == "0.26.1"
    assert items[0]["app_source"] == "0.25.0"
    assert items[0]["app"] == "0.26.0"


def test_parse_changes_block_strips_trailing_sentence_period_even_on_a_single_line(libupgradedoccomments: ModuleType):
    """A trailing sentence period is stripped from single-line items too."""
    text = "# Changes:\n#   1. curl 8.20.0 -> 8.21.0.\n"
    items = libupgradedoccomments.parse_changes_block(text)
    assert len(items) == 1
    assert items[0]["app_source"] == "8.20.0"
    assert items[0]["app"] == "8.21.0"


def test_parse_changes_block_trailing_remark_does_not_get_absorbed_into_last_item(libupgradedoccomments: ModuleType):
    """A single-space-indented trailing remark is not a continuation (2+ spaces), so it is not
    absorbed into the last item."""
    text = "# Changes:\n#   1. ZAC 5.0.2 -> 5.4.3\n# See docs/_UPGRADE_PATHS/...\n"
    items = libupgradedoccomments.parse_changes_block(text)
    assert len(items) == 1
    assert items[0]["name"] == "ZAC"
    assert "See docs" not in items[0]["name"]


def test_parse_changes_block_last_item_with_no_trailing_hash_line_still_finalizes(libupgradedoccomments: ModuleType):
    """The last item is finalized even when nothing follows it."""
    text = "# Changes:\n#   1. ZAC 5.0.2 -> 5.4.3"
    items = libupgradedoccomments.parse_changes_block(text)
    assert len(items) == 1
    assert items[0]["name"] == "ZAC"
