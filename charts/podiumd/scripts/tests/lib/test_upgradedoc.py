"""lib.upgradedoc — table-row parsing, cell version extraction, fuzzy
dependency matching, and app-version lookup."""


# --- normalize_version / normalize_name / words_of ---

def test_normalize_version_strips_v_prefix(libupgradedoc):
    assert libupgradedoc.normalize_version("v0.9.313") == "0.9.313"
    assert libupgradedoc.normalize_version("5.4.3") == "5.4.3"
    assert libupgradedoc.normalize_version(None) is None


def test_normalize_name_strips_punctuation(libupgradedoc):
    assert libupgradedoc.normalize_name("ZAC (Zaakafhandelcomponent)") == "zaczaakafhandelcomponent"


def test_words_of_splits_on_non_alnum(libupgradedoc):
    assert libupgradedoc.words_of("zgw-office-addin-frontend") == ["zgw", "office", "addin", "frontend"]


# --- extract_target_version / extract_source_version ---

def test_extract_versions_arrow_cell(libupgradedoc):
    assert libupgradedoc.extract_source_version("5.0.2 → 5.4.3") == "5.0.2"
    assert libupgradedoc.extract_target_version("5.0.2 → 5.4.3") == "5.4.3"


def test_extract_versions_unchanged_cell(libupgradedoc):
    assert libupgradedoc.extract_source_version("1.0.297 (unchanged)") == "1.0.297"
    assert libupgradedoc.extract_target_version("1.0.297 (unchanged)") == "1.0.297"


def test_extract_versions_backtick_cell(libupgradedoc):
    assert libupgradedoc.extract_target_version("`0.0.92`") == "0.0.92"


# --- parse_upgrade_doc_rows ---

TABLE = """\
# Upgrade guide

## Component versions (4.9.0 vs 4.8.5)

| Component | App version | Helm chart | Notes |
| --- | --- | --- | --- |
| ZAC (Zaakafhandelcomponent) | 5.0.2 → 5.4.3 | 1.0.297 (unchanged) | ACR mirror only |
| ZGW Office Add-in (frontend + backend) | v0.9.313 → 0.11.0 | 0.0.89 → 0.0.92 | ACR mirror only |
"""


def test_parse_upgrade_doc_rows_parses_all_rows(libupgradedoc):
    rows = libupgradedoc.parse_upgrade_doc_rows(TABLE)
    assert len(rows) == 2
    assert rows[0]["name"] == "ZAC (Zaakafhandelcomponent)"
    assert rows[0]["app_source"] == "5.0.2"
    assert rows[0]["app"] == "5.4.3"
    assert rows[0]["chart_source"] == "1.0.297"
    assert rows[0]["chart"] == "1.0.297"


def test_parse_upgrade_doc_rows_includes_line_index(libupgradedoc):
    rows = libupgradedoc.parse_upgrade_doc_rows(TABLE)
    lines = TABLE.splitlines()
    assert lines[rows[0]["line_index"]] == \
        "| ZAC (Zaakafhandelcomponent) | 5.0.2 → 5.4.3 | 1.0.297 (unchanged) | ACR mirror only |"


def test_parse_upgrade_doc_rows_skips_header_and_separator(libupgradedoc):
    rows = libupgradedoc.parse_upgrade_doc_rows(TABLE)
    names = [r["name"] for r in rows]
    assert "Component" not in names
    assert not any(set(n) <= set("-: ") for n in names)


def test_parse_upgrade_doc_rows_no_table_returns_empty(libupgradedoc):
    assert libupgradedoc.parse_upgrade_doc_rows("# Upgrade guide\n\nJust prose.\n") == []


# --- match_dependency ---

def test_match_dependency_by_alias(libupgradedoc):
    deps = [{"name": "zaakafhandelcomponent", "alias": "zac"}]
    dep = libupgradedoc.match_dependency("ZAC (Zaakafhandelcomponent)", deps)
    assert dep["alias"] == "zac"


def test_match_dependency_prefers_longest_match(libupgradedoc):
    deps = [{"name": "openzaak"}, {"name": "openzaak-notificaties"}]
    dep = libupgradedoc.match_dependency("OpenZaak Notificaties", deps)
    assert dep["name"] == "openzaak-notificaties"


def test_match_dependency_no_match_returns_none(libupgradedoc):
    assert libupgradedoc.match_dependency("Totally Unknown Thing", [{"name": "zac"}]) is None


# --- image_tag / actual_app_version ---

def test_image_tag_nested_lookup(libupgradedoc):
    values = {"zac": {"image": {"tag": "5.4.3@sha256:abc"}}}
    assert libupgradedoc.image_tag(values, "zac", "image", "tag") == "5.4.3@sha256:abc"
    assert libupgradedoc.image_tag(values, "zac", "missing", "tag") is None
    assert libupgradedoc.image_tag("not-a-dict", "x") is None


def test_actual_app_version_single_image(libupgradedoc):
    assert libupgradedoc.actual_app_version({"zac": {"image": {"tag": "5.4.3@sha256:abc"}}}, "zac") == "5.4.3"


def test_actual_app_version_frontend_backend_lockstep(libupgradedoc):
    values = {"zgw-office-addin": {"frontend": {"image": {"tag": "v0.9.352@sha256:abc"}}}}
    assert libupgradedoc.actual_app_version(values, "zgw-office-addin") == "v0.9.352"


def test_actual_app_version_missing_returns_none(libupgradedoc):
    assert libupgradedoc.actual_app_version({}, "missing") is None


# --- find_image_tag_paths ---

def test_find_image_tag_paths_finds_nested_images(libupgradedoc):
    values = {
        "zac": {
            "image": {"tag": "5.1.0@sha256:aaaa"},
            "opa": {"image": {"tag": "1.19.0-static@sha256:bbbb"}},
        },
    }
    paths = dict(libupgradedoc.find_image_tag_paths(values))
    assert paths[("zac",)] == "5.1.0@sha256:aaaa"
    assert paths[("zac", "opa")] == "1.19.0-static@sha256:bbbb"


def test_find_image_tag_paths_ignores_tagless_image_blocks(libupgradedoc):
    values = {"zac": {"image": {"repository": "x"}}}
    assert dict(libupgradedoc.find_image_tag_paths(values)) == {}


def test_find_image_tag_paths_walks_lists(libupgradedoc):
    values = {"items": [{"image": {"tag": "1.0@sha256:aaaa"}}]}
    paths = dict(libupgradedoc.find_image_tag_paths(values))
    assert paths[("items", "0")] == "1.0@sha256:aaaa"


# --- resolve_entry_path ---

def test_resolve_entry_path_exact_match(libupgradedoc):
    paths = [("zac",), ("zgw-office-addin", "frontend"), ("zgw-office-addin", "backend")]
    assert libupgradedoc.resolve_entry_path("zgw-office-addin-frontend", paths) == \
        ("zgw-office-addin", "frontend")


def test_resolve_entry_path_last_word_must_match(libupgradedoc):
    paths = [("zac", "solr-operator", "solr"), ("zac", "solr-operator", "zookeeper-operator", "zookeeper")]
    assert libupgradedoc.resolve_entry_path("zac-solr", paths) == ("zac", "solr-operator", "solr")


def test_resolve_entry_path_no_match_returns_none(libupgradedoc):
    assert libupgradedoc.resolve_entry_path("totally-unrelated", [("zac",)]) is None


# --- find_preceding_comment ---

def test_find_preceding_comment_joins_consecutive_comment_lines(libupgradedoc):
    lines = [
        "# ZAC OPA sidecar\n",
        "# 1.17.1-static -> 1.19.0-static\n",
        "- name: opa\n",
    ]
    assert libupgradedoc.find_preceding_comment(lines, 2) == \
        "# ZAC OPA sidecar # 1.17.1-static -> 1.19.0-static"


def test_find_preceding_comment_stops_at_blank_line(libupgradedoc):
    lines = [
        "# unrelated previous entry's comment\n",
        "\n",
        "# ZAC — 5.0.1 -> 5.1.0\n",
        "- name: zac\n",
    ]
    assert libupgradedoc.find_preceding_comment(lines, 3) == "# ZAC — 5.0.1 -> 5.1.0"


def test_find_preceding_comment_none_when_absent(libupgradedoc):
    lines = ["- name: zac\n"]
    assert libupgradedoc.find_preceding_comment(lines, 0) == ""


# --- diff_keys / flatten_leaf_keys / pair_renames ---

def test_diff_keys_finds_added_and_removed(libupgradedoc):
    baseline = {"a": 1, "b": {"x": 1}}
    current = {"a": 1, "c": {"y": 1}}
    diffs = sorted(libupgradedoc.diff_keys(baseline, current))
    assert ("added", ("c",)) in diffs
    assert ("removed", ("b",)) in diffs


def test_diff_keys_ignores_scalar_value_changes(libupgradedoc):
    baseline = {"a": 1}
    current = {"a": 2}
    assert list(libupgradedoc.diff_keys(baseline, current)) == []


def test_diff_keys_recurses_into_shared_keys(libupgradedoc):
    baseline = {"a": {"x": 1}}
    current = {"a": {"x": 1, "y": 2}}
    assert list(libupgradedoc.diff_keys(baseline, current)) == [("added", ("a", "y"))]


def test_flatten_leaf_keys_collects_all_nested_names(libupgradedoc):
    node = {"host": "h", "auth": {"user": "u", "password": "p"}}
    assert libupgradedoc.flatten_leaf_keys(node) == {"host", "auth", "user", "password"}


def test_flatten_leaf_keys_walks_lists(libupgradedoc):
    node = [{"a": 1}, {"b": 2}]
    assert libupgradedoc.flatten_leaf_keys(node) == {"a", "b"}


def test_pair_renames_pairs_similar_subtrees(libupgradedoc):
    baseline = {"mi": {"sftp": {"host": "h", "user": "u", "password": "p"}}}
    current = {"mi": {"transfer": {"host": "h", "user": "u", "password": "p"}}}
    added = [("mi", "transfer")]
    removed = [("mi", "sftp")]
    renamed, added_left, removed_left = libupgradedoc.pair_renames(added, removed, baseline, current)
    assert renamed == [(("mi", "sftp"), ("mi", "transfer"))]
    assert added_left == [] and removed_left == []


def test_pair_renames_leaves_unrelated_add_remove_alone(libupgradedoc):
    baseline = {"a": {"x": 1}}
    current = {"b": {"totally": "different", "shape": True}}
    added = [("b",)]
    removed = [("a",)]
    renamed, added_left, removed_left = libupgradedoc.pair_renames(added, removed, baseline, current)
    assert renamed == []
    assert added_left == [("b",)] and removed_left == [("a",)]


# --- parse_changes_block ---

def test_parse_changes_block_parses_numbered_items(libupgradedoc):
    text = (
        "# Baseline: podiumd 4.8.5.\n"
        "#\n"
        "# Changes:\n"
        "#   1. ZAC 5.0.2 -> 5.4.3 (chart 1.0.297, unchanged).\n"
        "#   2. ZGW Office Add-in v0.9.313 -> 0.11.0 (chart 0.0.89 -> 0.0.92).\n"
        "#\n"
        "# See docs/_UPGRADE_PATHS/...\n"
    )
    items = libupgradedoc.parse_changes_block(text)
    assert len(items) == 2
    assert items[0]["name"] == "ZAC"
    assert items[0]["app_source"] == "5.0.2"
    assert items[0]["app"] == "5.4.3"
    assert items[1]["chart_source"] == "0.0.89"
    assert items[1]["chart"] == "0.0.92"


def test_parse_changes_block_no_header_returns_empty(libupgradedoc):
    assert libupgradedoc.parse_changes_block("# just a header\n# no changes block\n") == []


def test_parse_changes_block_version_with_dot_not_mistaken_for_new_item(libupgradedoc):
    text = (
        "# Changes:\n"
        "#   1. OPA 1.17.1-static -> 1.19.0-static\n"
        "#   2. ZAC 5.0.2 -> 5.4.3\n"
    )
    items = libupgradedoc.parse_changes_block(text)
    assert len(items) == 2
    assert items[0]["app"] == "1.19.0-static"
    assert items[1]["app"] == "5.4.3"


# --- canonical_version_cell ---

def test_canonical_version_cell_arrow_form(libupgradedoc):
    assert libupgradedoc.canonical_version_cell("5.0.2", "5.1.0") == "5.0.2 → 5.1.0"


def test_canonical_version_cell_unchanged_form(libupgradedoc):
    assert libupgradedoc.canonical_version_cell("1.0.297", "1.0.297") == "1.0.297 (unchanged)"


# --- find_preceding_comment_line / replace_version_pair ---

def test_find_preceding_comment_line_finds_arrow_comment(libupgradedoc):
    lines = ["# ZAC — 5.0.1 -> 5.1.0\n", "- name: zac\n"]
    assert libupgradedoc.find_preceding_comment_line(lines, 1) == 0


def test_find_preceding_comment_line_none_when_no_arrow(libupgradedoc):
    lines = ["#repository:\n", "- name: zac\n"]
    assert libupgradedoc.find_preceding_comment_line(lines, 1) is None


def test_replace_version_pair_preserves_prefix_and_arrow_style(libupgradedoc):
    assert libupgradedoc.replace_version_pair("# ZAC — 5.0.1 -> 5.1.0\n", "5.0.2", "5.1.0") == \
        "# ZAC — 5.0.2 -> 5.1.0\n"
    assert libupgradedoc.replace_version_pair("# ZAC — 5.0.1 → 5.1.0\n", "5.0.2", "5.1.0") == \
        "# ZAC — 5.0.2 → 5.1.0\n"


def test_replace_version_pair_no_match_returns_unchanged(libupgradedoc):
    line = "# no version pair here\n"
    assert libupgradedoc.replace_version_pair(line, "1.0.0", "2.0.0") == line
