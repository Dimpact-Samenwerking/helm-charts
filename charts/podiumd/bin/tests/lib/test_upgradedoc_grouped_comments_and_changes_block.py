"""lib.upgradedoc -- preceding-comment/grouped-comment lookup and
Changes-block parsing."""

from types import ModuleType

# --- path_display_name ---


def test_path_display_name_primary_dependency_image_uses_bare_key(libupgradedoccomments: ModuleType):
    """A dependency's own primary image (image_paths_for's default
    "image" path) displays as just its values key — the same name every
    "component "<key>" changed vs ..." message elsewhere already uses,
    never the dotted values.yaml path."""
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac", "version": "1.0.0"}]
    assert libupgradedoccomments.path_display_name(("zac", "image"), deps, canonical_names={}) == "zac"


def test_path_display_name_sidecar_uses_canonical_name(libupgradedoccomments: ModuleType):
    """A nested sidecar path resolves via canonical_names
    (canonical_sidecar_row_names's own {name: path} mapping) to its
    "<key> - <basename>" doc name."""
    deps = [{"name": "redis-operator", "version": "1.0.0"}]
    canonical_names = {"redis-operator - redis": ("redis-operator", "redis-ha", "image")}
    assert (
        libupgradedoccomments.path_display_name(("redis-operator", "redis-ha", "image"), deps, canonical_names)
        == "redis-operator - redis"
    )


def test_path_display_name_global_uses_bare_basename(libupgradedoccomments: ModuleType):
    """A shared "global" image resolves to canonical_names' bare
    basename, with no "<key> -" prefix at all."""
    canonical_names = {"curl": ("global", "images", "curl", "image")}
    assert (
        libupgradedoccomments.path_display_name(
            ("global", "images", "curl", "image"), deps=[], canonical_names=canonical_names
        )
        == "curl"
    )


def test_path_display_name_falls_back_to_dotted_path(libupgradedoccomments: ModuleType):
    """A path covered by neither a real dependency's primary image nor
    canonical_names (e.g. an image with no vendored/own repository to
    resolve a basename from) falls back to the raw dotted path rather
    than guessing at a name."""
    assert (
        libupgradedoccomments.path_display_name(("mystery", "nested", "image"), deps=[], canonical_names={})
        == "mystery.nested.image"
    )


def test_path_display_name_version_paths_for_field_uses_bare_key(libupgradedoccomments: ModuleType):
    """A dependency whose real app version comes from lib.chart.
    version_paths_for's own bare-scalar fallback (no "image: {tag}"
    block at all — redis-operator's own split "redisOperator.imageTag")
    is ALSO its primary, displaying as just its values key — the exact
    same convention actual_app_version already uses for -upgrade.md's
    own row/Changes heading (there literally named "redis-operator").
    Before _is_dependency_primary_rel_path existed, this path matched
    neither image_paths_for nor canonical_names and fell back to the
    raw dotted path, real case reported live against images-4.9.0.yaml."""
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
    """The grouping predicate check_images_manifest_format and friends
    actually use: same top-level component AND same declared version —
    matching declared versions is what tells a lockstep multi-image bump
    (zgw-office-addin frontend/backend, always identical) apart from two
    independently-versioned images that just share a values-tree prefix
    (zac vs. its zac.opa sidecar)."""
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
    """A ZAC entry right after ZGW's group, with no comment of its own, must
    NOT inherit ZGW's comment just because it's the immediately preceding
    entry — they resolve to different components."""
    lines = [*ZGW_GROUPED_LINES, "\n", "- name: zac\n", '  version: "5.1.0"\n']
    entries = [*ZGW_ENTRIES, {"name": "zac", "version": "5.1.0"}]
    entry_line_indices = [*ZGW_ENTRY_LINE_INDICES, 7]

    comment = libupgradedoccomments.find_grouped_preceding_comment(lines, entries, entry_line_indices, 2, same_group)
    assert comment == ""


def test_find_grouped_preceding_comment_does_not_override_own_distinct_comment(libupgradedoccomments: ModuleType):
    """ZAC's OPA sidecar has its own comment despite resolving to the same
    top-level component ("zac") as ZAC's main entry — its own comment must
    win, never be replaced by the main entry's comment."""
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
    """Same top-level component ("zac") is not enough on its own — the
    OPA sidecar's version differs from ZAC's own, so even with no comment
    of its own it must NOT inherit ZAC's comment (they're independently
    versioned, not one lockstep bump)."""
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
    """Added, removed and shared keys each come out sorted, not in set
    order, so pair_renames sees the same input order in every process."""
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
    """A key whose value is a dict or list is not a leaf: counting it would
    inflate the similarity ratio pair_renames uses."""
    node = {"a": {"x": 1, "y": [{"z": 2}]}}
    assert libupgradedoccomments.flatten_leaf_keys(node) == {"x", "z"}


def test_pair_renames_ignores_shared_intermediate_keys(libupgradedoccomments: ModuleType):
    """Two blocks that only share an intermediate key name ("auth") and no
    leaf key are an unrelated add and remove, not a rename."""
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


def test_parse_changes_block_no_header_returns_empty(libupgradedoccomments: ModuleType):
    assert libupgradedoccomments.parse_changes_block("# just a header\n# no changes block\n") == []


def test_parse_changes_block_version_with_dot_not_mistaken_for_new_item(libupgradedoccomments: ModuleType):
    text = "# Changes:\n#   1. OPA 1.17.1-static -> 1.19.0-static\n#   2. ZAC 5.0.2 -> 5.4.3\n"
    items = libupgradedoccomments.parse_changes_block(text)
    assert len(items) == 2
    assert items[0]["app"] == "1.19.0-static"
    assert items[1]["app"] == "5.4.3"


def test_parse_changes_block_joins_a_wrapped_version_pair(libupgradedoccomments: ModuleType):
    """Regression test: an item whose own "<source> -> <target>" pair
    sits on a WRAPPED continuation line (not the numbered line itself)
    used to be silently unparseable — extract_source_version/
    extract_target_version's own "no arrow found" fallback grabbed the
    item's own leading word ("nginx-unprivileged") as a fake version,
    since the numbered line alone never had an arrow in it at all."""
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
    """The same continuation-joining fixes a second, previously silent
    gap: a "(chart ...)" span whose own closing paren is on the wrapped
    line never matched at all before (chart_source/chart just stayed
    None, so the chart comparison was silently skipped rather than
    actually verified)."""
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
    """Regression test: a chart-only item that states its version pair as
    a bare "chart <source> -> <target>" clause (no "(chart ...)" parens
    at all) must never have that pair mistaken for the item's own APP
    version — the real-world case this was found from: "ECK Stack
    (kiss-eck) chart 0.19.0 -> 0.20.0 (no image change of its own)."
    used to grab "0.19.0 -> 0.20.0" as a fake app version once eck-stack
    became resolvable via COMPONENT_VERSION_PATHS, silently comparing it
    against the real (unrelated) app version and reporting a bogus
    mismatch."""
    text = "# Changes:\n#   6. ECK Stack (kiss-eck) chart 0.19.0 -> 0.20.0 (no image change of\n#      its own).\n"
    items = libupgradedoccomments.parse_changes_block(text)
    assert len(items) == 1
    assert items[0]["chart_source"] == "0.19.0"
    assert items[0]["chart"] == "0.20.0"
    assert items[0]["app_source"] is None
    assert items[0]["app"] is None


def test_parse_changes_block_chart_pair_before_app_pair_both_extracted_correctly(libupgradedoccomments: ModuleType):
    """The real-world redis-operator case: BOTH a bare chart clause and a
    real app-version pair appear in the same sentence, chart first — the
    chart pair must not be mistaken for the app pair, and the real app
    pair (the second one) must still be found correctly."""
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
    """The trailing-period fix isn't specific to wrapped items — any
    Changes item whose version is the last thing before its own
    sentence-ending period, single-line or not, must have it stripped."""
    text = "# Changes:\n#   1. curl 8.20.0 -> 8.21.0.\n"
    items = libupgradedoccomments.parse_changes_block(text)
    assert len(items) == 1
    assert items[0]["app_source"] == "8.20.0"
    assert items[0]["app"] == "8.21.0"


def test_parse_changes_block_trailing_remark_does_not_get_absorbed_into_last_item(libupgradedoccomments: ModuleType):
    """A trailing "# See docs/..." remark right after the last item, with
    no blank "#" line separating them, must never be swallowed into that
    item's own text — it's indented with the ordinary single-space
    comment convention, not the 2+-space continuation indent, so it's
    distinguishable from a real wrapped continuation line."""
    text = "# Changes:\n#   1. ZAC 5.0.2 -> 5.4.3\n# See docs/_UPGRADE_PATHS/...\n"
    items = libupgradedoccomments.parse_changes_block(text)
    assert len(items) == 1
    assert items[0]["name"] == "ZAC"
    assert "See docs" not in items[0]["name"]


def test_parse_changes_block_last_item_with_no_trailing_hash_line_still_finalizes(libupgradedoccomments: ModuleType):
    """The very last item in the block, with nothing at all following it
    (no blank "#" line, no trailing remark, file just ends) must still
    be finalized — not silently dropped because there was no later line
    to trigger it."""
    text = "# Changes:\n#   1. ZAC 5.0.2 -> 5.4.3"
    items = libupgradedoccomments.parse_changes_block(text)
    assert len(items) == 1
    assert items[0]["name"] == "ZAC"
