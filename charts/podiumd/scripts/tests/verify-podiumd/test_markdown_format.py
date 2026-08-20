"""check_markdown_format, check_doc_title, check_companion_doc,
check_baseline_doc_set."""


def test_markdown_format_passes_for_well_formed_doc(vp, tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text("# Title\n\nSome content.\n\n```yaml\nfoo: bar\n```\n")
    assert vp.check_markdown_format(doc) == []


def test_markdown_format_flags_empty_file(vp, tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text("   \n\n")
    issues = vp.check_markdown_format(doc)
    assert issues == ["file is empty"]


def test_markdown_format_flags_missing_heading(vp, tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text("Not a heading\n\ncontent\n")
    issues = vp.check_markdown_format(doc)
    assert any("level-1 heading" in i for i in issues)


def test_markdown_format_flags_unbalanced_fence(vp, tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text("# Title\n\n```yaml\nfoo: bar\n")
    issues = vp.check_markdown_format(doc)
    assert any("unbalanced" in i for i in issues)


def test_markdown_format_does_not_false_positive_on_version_like_continuation(vp, tmp_path):
    """A continuation line like "1.17.1-static" must not itself be mistaken
    for markdown structure that breaks the format check."""
    doc = tmp_path / "doc.md"
    doc.write_text("# Title\n\n#   1. ZAC 5.0.2 -> 5.4.3.\n#      1.17.1-static -> 1.19.0-static.\n")
    assert vp.check_markdown_format(doc) == []


def test_doc_title_passes_when_versions_match(vp, tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text("# Upgrade guide: PodiumD 4.8.5 → 4.9.0\n\ncontent\n")
    assert vp.check_doc_title(doc, "4.8.5", "4.9.0") == []


def test_doc_title_accepts_ascii_arrow(vp, tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text("# Upgrade guide: PodiumD 4.8.5 -> 4.9.0\n")
    assert vp.check_doc_title(doc, "4.8.5", "4.9.0") == []


def test_doc_title_flags_stale_baseline(vp, tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text("# Upgrade guide: PodiumD 4.8.2 → 4.9.0\n")
    issues = vp.check_doc_title(doc, "4.8.5", "4.9.0")
    assert len(issues) == 1
    assert "does not read" in issues[0]


def test_doc_title_handles_empty_file(vp, tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text("")
    issues = vp.check_doc_title(doc, "4.8.5", "4.9.0")
    assert len(issues) == 1


def test_check_companion_doc_missing_file(vp, tmp_path):
    name, issues = vp.check_companion_doc(tmp_path, "4.8.5", "4.9.0", "gemeente-specific")
    assert name == "4.8.5-to-4.9.0-gemeente-specific.md"
    assert "does not exist" in issues[0]


def test_check_companion_doc_existing_correct_file(vp, tmp_path):
    (tmp_path / "4.8.5-to-4.9.0-values-deltas.md").write_text(
        "# Values deltas — PodiumD 4.8.5 → 4.9.0\n\nNo changes.\n")
    name, issues = vp.check_companion_doc(tmp_path, "4.8.5", "4.9.0", "values-deltas")
    assert name == "4.8.5-to-4.9.0-values-deltas.md"
    assert issues == []


def test_check_baseline_doc_set_all_three_missing(vp, tmp_path):
    issues = vp.check_baseline_doc_set(tmp_path, "4.8.5", "4.9.0")
    assert len(issues) == 3
    assert all("does not exist" in i for i in issues)


def test_check_baseline_doc_set_all_present_and_valid(vp, tmp_path):
    for suffix, title in [
        ("upgrade", "Upgrade guide"),
        ("gemeente-specific", "Gemeente-specific notes"),
        ("values-deltas", "Values deltas"),
    ]:
        (tmp_path / f"4.8.5-to-4.9.0-{suffix}.md").write_text(
            f"# {title} — PodiumD 4.8.5 → 4.9.0\n\ncontent\n")
    assert vp.check_baseline_doc_set(tmp_path, "4.8.5", "4.9.0") == []


def test_check_baseline_doc_set_reports_malformed_doc(vp, tmp_path):
    (tmp_path / "4.8.5-to-4.9.0-upgrade.md").write_text("no heading here\n")
    (tmp_path / "4.8.5-to-4.9.0-gemeente-specific.md").write_text("# Title\n\ncontent\n")
    (tmp_path / "4.8.5-to-4.9.0-values-deltas.md").write_text("# Title\n\ncontent\n")
    issues = vp.check_baseline_doc_set(tmp_path, "4.8.5", "4.9.0")
    assert len(issues) == 1
    assert "level-1 heading" in issues[0]
