"""diff_keys, flatten_leaf_keys, pair_renames, check_values_deltas_content —
the values.yaml structural-diff machinery, including the real mi.sftp ->
mi.transfer rename example from the docs."""


def test_diff_keys_identical_trees(libupgradedoc):
    tree = {"a": {"b": 1}}
    assert list(libupgradedoc.diff_keys(tree, tree)) == []


def test_diff_keys_added_and_removed_at_same_level(libupgradedoc):
    baseline = {"a": 1, "b": 2}
    current = {"a": 1, "c": 3}
    result = set(libupgradedoc.diff_keys(baseline, current))
    assert result == {("added", ("c",)), ("removed", ("b",))}


def test_diff_keys_reports_shallowest_differing_level(libupgradedoc):
    """A whole new/removed block is reported once, not leaf-by-leaf."""
    baseline = {"mi": {"sftp": {"host": "x", "user": "y", "password": "z"}}}
    current = {"mi": {"transfer": {"mode": "sftp-password", "host": "x"}}}
    result = list(libupgradedoc.diff_keys(baseline, current))
    assert ("removed", ("mi", "sftp")) in result
    assert ("added", ("mi", "transfer")) in result
    # must NOT recurse into "transfer" to also report "mode" as separately added
    assert not any(path[:2] == ("mi", "transfer") and len(path) > 2 for _, path in result)


def test_diff_keys_recurses_into_keys_present_in_both(libupgradedoc):
    baseline = {"mi": {"enabled": True, "sftp": {"host": "old"}}}
    current = {"mi": {"enabled": True, "sftp": {"host": "old", "port": 22}}}
    result = list(libupgradedoc.diff_keys(baseline, current))
    assert result == [("added", ("mi", "sftp", "port"))]


def test_diff_keys_scalar_value_change_is_not_reported(libupgradedoc):
    baseline = {"a": 1}
    current = {"a": 2}
    assert list(libupgradedoc.diff_keys(baseline, current)) == []


def test_diff_keys_non_dict_nodes_yield_nothing(libupgradedoc):
    assert list(libupgradedoc.diff_keys("x", "y")) == []
    assert list(libupgradedoc.diff_keys(["a"], ["b"])) == []


def test_flatten_leaf_keys_collects_all_nested_key_names(libupgradedoc):
    node = {"host": "x", "auth": {"user": "y", "password": "z"}}
    assert libupgradedoc.flatten_leaf_keys(node) == {"host", "auth", "user", "password"}


def test_flatten_leaf_keys_walks_lists(libupgradedoc):
    node = [{"a": 1}, {"b": 2}]
    assert libupgradedoc.flatten_leaf_keys(node) == {"a", "b"}


def test_flatten_leaf_keys_scalar_is_empty(libupgradedoc):
    assert libupgradedoc.flatten_leaf_keys("scalar") == set()


def test_pair_renames_detects_similar_blocks(libupgradedoc):
    """The real mi.sftp -> mi.transfer example: different key, but the new
    block's leaf keys substantially overlap with the old one's."""
    baseline = {"mi": {"sftp": {"host": "x", "user": "y", "password": "z"}}}
    current = {"mi": {"transfer": {"mode": "sftp-password", "host": "x", "user": "y", "password": "z"}}}
    added = [("mi", "transfer")]
    removed = [("mi", "sftp")]
    renamed, added_left, removed_left = libupgradedoc.pair_renames(added, removed, baseline, current)
    assert renamed == [(("mi", "sftp"), ("mi", "transfer"))]
    assert added_left == []
    assert removed_left == []


def test_pair_renames_does_not_pair_dissimilar_blocks(libupgradedoc):
    baseline = {"mi": {"old": {"totally": 1, "different": 2}}}
    current = {"mi": {"new": {"unrelated": 3, "fields": 4}}}
    added = [("mi", "new")]
    removed = [("mi", "old")]
    renamed, added_left, removed_left = libupgradedoc.pair_renames(added, removed, baseline, current)
    assert renamed == []
    assert added_left == [("mi", "new")]
    assert removed_left == [("mi", "old")]


def test_pair_renames_pairs_identical_scalars(libupgradedoc):
    baseline = {"mi": {"oldName": "same-value"}}
    current = {"mi": {"newName": "same-value"}}
    added = [("mi", "newName")]
    removed = [("mi", "oldName")]
    renamed, added_left, removed_left = libupgradedoc.pair_renames(added, removed, baseline, current)
    assert renamed == [(("mi", "oldName"), ("mi", "newName"))]


def test_pair_renames_ignores_different_parent_paths(libupgradedoc):
    baseline = {"mi": {"a": {"x": 1}}}
    current = {"other": {"b": {"x": 1}}}
    added = [("other", "b")]
    removed = [("mi", "a")]
    renamed, added_left, removed_left = libupgradedoc.pair_renames(added, removed, baseline, current)
    assert renamed == []
    assert added_left == [("other", "b")]
    assert removed_left == [("mi", "a")]


# --- check_values_deltas_content ---

def test_values_deltas_content_no_changes_is_clean(libdocsconsistency, tmp_path):
    doc = tmp_path / "values-deltas.md"
    doc.write_text("# Values deltas\n\nNo gemeente podiumd.yml changes are required for this hop.\n")
    values = {"mi": {"sftp": {"host": "x"}}}
    assert libdocsconsistency.check_values_deltas_content(doc, {"mi"}, values, values) == []


def test_values_deltas_content_rename_mentioned_both_sides_passes(libdocsconsistency, tmp_path):
    doc = tmp_path / "values-deltas.md"
    doc.write_text("Rename `mi.sftp` to `mi.transfer`, add `mi.transfer.mode`.\n")
    baseline = {"mi": {"sftp": {"host": "x", "user": "y", "password": "z"}}}
    current = {"mi": {"transfer": {"mode": "sftp-password", "host": "x", "user": "y", "password": "z"}}}
    assert libdocsconsistency.check_values_deltas_content(doc, {"mi"}, baseline, current) == []


def test_values_deltas_content_flags_unmentioned_rename(libdocsconsistency, tmp_path):
    doc = tmp_path / "values-deltas.md"
    doc.write_text("# Values deltas\n\nNo gemeente podiumd.yml changes are required for this hop.\n")
    baseline = {"mi": {"sftp": {"host": "x", "user": "y", "password": "z"}}}
    current = {"mi": {"transfer": {"mode": "sftp-password", "host": "x", "user": "y", "password": "z"}}}
    issues = libdocsconsistency.check_values_deltas_content(doc, {"mi"}, baseline, current)
    assert any("appears renamed" in i for i in issues)
    assert any("claims" in i and "No gemeente" in i for i in issues)


def test_values_deltas_content_flags_unmentioned_addition(libdocsconsistency, tmp_path):
    doc = tmp_path / "values-deltas.md"
    doc.write_text("# Values deltas\n\nNothing relevant mentioned.\n")
    baseline = {"zac": {"brpApi": {}}}
    current = {"zac": {"brpApi": {"logLevel": "OFF"}}}
    issues = libdocsconsistency.check_values_deltas_content(doc, {"zac"}, baseline, current)
    assert any('key "zac.brpApi.logLevel" was added' in i for i in issues)


def test_values_deltas_content_flags_unmentioned_removal(libdocsconsistency, tmp_path):
    doc = tmp_path / "values-deltas.md"
    doc.write_text("# Values deltas\n\nNothing relevant mentioned.\n")
    baseline = {"zac": {"brpApi": {"protocollering": {"verwerking": {"extendWithZaaktype": False}}}}}
    current = {"zac": {"brpApi": {"protocollering": {"verwerking": {}}}}}
    issues = libdocsconsistency.check_values_deltas_content(doc, {"zac"}, baseline, current)
    assert any(
        'key "zac.brpApi.protocollering.verwerking.extendWithZaaktype" was removed' in i
        for i in issues
    )


def test_values_deltas_content_mentioned_addition_passes(libdocsconsistency, tmp_path):
    doc = tmp_path / "values-deltas.md"
    doc.write_text("New field `zac.brpApi.logLevel`, defaults to `OFF`.\n")
    baseline = {"zac": {"brpApi": {}}}
    current = {"zac": {"brpApi": {"logLevel": "OFF"}}}
    assert libdocsconsistency.check_values_deltas_content(doc, {"zac"}, baseline, current) == []


def test_values_deltas_content_ignores_untracked_components(libdocsconsistency, tmp_path):
    doc = tmp_path / "values-deltas.md"
    doc.write_text("# Values deltas\n\nNo gemeente podiumd.yml changes are required for this hop.\n")
    baseline = {"unrelated": {"a": 1}}
    current = {"unrelated": {"b": 2}}
    # "unrelated" isn't in changed_component_keys, so its diff must be ignored
    assert libdocsconsistency.check_values_deltas_content(doc, {"zac"}, baseline, current) == []
