"""check_duplicate_keys — including the list-item scoping fix: sibling list
items sharing a key name (e.g. every item having its own "value:") must never
be treated as duplicates of each other."""


def write_values(tmp_path, content):
    (tmp_path / "values.yaml").write_text(content)
    return tmp_path


def test_no_duplicates_passes(vp, tmp_path):
    chart_dir = write_values(tmp_path, "zac:\n  image:\n    tag: 5.4.3\n")
    ok, detail = vp.check_duplicate_keys(chart_dir)
    assert ok is True
    assert "0 duplicates" in detail


def test_genuine_duplicate_at_root_is_caught(vp, tmp_path):
    chart_dir = write_values(tmp_path, "zac:\n  a: 1\nzac:\n  b: 2\n")
    ok, detail = vp.check_duplicate_keys(chart_dir)
    assert ok is False
    assert "1 duplicate" in detail


def test_genuine_duplicate_nested_is_caught(vp, tmp_path):
    content = (
        "zac:\n"
        "  image:\n"
        "    tag: 5.4.3\n"
        "  image:\n"
        "    tag: 5.5.0\n"
    )
    chart_dir = write_values(tmp_path, content)
    ok, detail = vp.check_duplicate_keys(chart_dir)
    assert ok is False
    assert "2 duplicate" in detail  # both "image" and "tag" collide


def test_list_items_sharing_key_names_are_not_false_positives(vp, tmp_path):
    """Regression test for the bug found in /helm-dupecheck's ported algorithm:
    naive scoping treated every list item's "value:"/"mountPath:" as
    colliding with its siblings."""
    content = (
        "additionalOptions:\n"
        "  - name: foo\n"
        "    value: bar\n"
        "  - name: baz\n"
        "    value: qux\n"
        "volumeMounts:\n"
        "  - name: a\n"
        "    mountPath: /a\n"
        "    subPath: a\n"
        "  - name: b\n"
        "    mountPath: /b\n"
        "    subPath: b\n"
    )
    chart_dir = write_values(tmp_path, content)
    ok, detail = vp.check_duplicate_keys(chart_dir)
    assert ok is True, detail
    assert "0 duplicates" in detail


def test_duplicate_key_within_a_single_list_item_is_still_caught(vp, tmp_path):
    content = (
        "list:\n"
        "  - name: foo\n"
        "    value: bar\n"
        "    value: baz\n"
    )
    chart_dir = write_values(tmp_path, content)
    ok, detail = vp.check_duplicate_keys(chart_dir)
    assert ok is False
    assert "1 duplicate" in detail


def test_comments_are_ignored(vp, tmp_path):
    content = "zac:\n  # image:\n  image:\n    tag: 5.4.3\n"
    chart_dir = write_values(tmp_path, content)
    ok, _ = vp.check_duplicate_keys(chart_dir)
    assert ok is True
