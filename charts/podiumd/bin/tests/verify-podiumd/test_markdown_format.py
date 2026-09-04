"""check_markdown_format, check_doc_title, check_companion_doc,
check_baseline_doc_set."""


def test_markdown_format_passes_for_well_formed_doc(libdocsconsistency, tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text("# Title\n\nSome content.\n\n```yaml\nfoo: bar\n```\n")
    assert libdocsconsistency.check_markdown_format(doc) == []


def test_markdown_format_flags_empty_file(libdocsconsistency, tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text("   \n\n")
    issues = libdocsconsistency.check_markdown_format(doc)
    assert issues == ["file is empty"]


def test_markdown_format_flags_missing_heading(libdocsconsistency, tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text("Not a heading\n\ncontent\n")
    issues = libdocsconsistency.check_markdown_format(doc)
    assert any("level-1 heading" in i for i in issues)


def test_markdown_format_flags_unbalanced_fence(libdocsconsistency, tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text("# Title\n\n```yaml\nfoo: bar\n")
    issues = libdocsconsistency.check_markdown_format(doc)
    assert any("unbalanced" in i for i in issues)


def test_markdown_format_counts_indented_fences(libdocsconsistency, tmp_path):
    """Upgrade docs nest ``` blocks under numbered list steps, so the fence
    is indented, not at column 0. A doc with one column-0 pair plus one
    indented pair is balanced (4 fences) and must not be flagged."""
    doc = tmp_path / "doc.md"
    doc.write_text(
        "# Title\n\n"
        "```sh\necho hi\n```\n\n"
        "1. Then run:\n\n"
        "   ```sh\n   echo step\n   ```\n"
    )
    assert libdocsconsistency.check_markdown_format(doc) == []


def test_markdown_format_flags_unbalanced_indented_fence(libdocsconsistency, tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text("# Title\n\n1. Run:\n\n   ```sh\n   echo hi\n")
    issues = libdocsconsistency.check_markdown_format(doc)
    assert any("unbalanced" in i for i in issues)


def test_markdown_format_does_not_false_positive_on_version_like_continuation(libdocsconsistency, tmp_path):
    """A continuation line like "1.17.1-static" must not itself be mistaken
    for markdown structure that breaks the format check."""
    doc = tmp_path / "doc.md"
    doc.write_text("# Title\n\n#   1. ZAC 5.0.2 -> 5.4.3.\n#      1.17.1-static -> 1.19.0-static.\n")
    assert libdocsconsistency.check_markdown_format(doc) == []


def test_doc_title_passes_when_versions_match(libdocsconsistency, tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text("# Upgrade guide: PodiumD 4.8.5 → 4.9.0\n\ncontent\n")
    assert libdocsconsistency.check_doc_title(doc, "4.8.5", "4.9.0") == []


def test_doc_title_accepts_ascii_arrow(libdocsconsistency, tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text("# Upgrade guide: PodiumD 4.8.5 -> 4.9.0\n")
    assert libdocsconsistency.check_doc_title(doc, "4.8.5", "4.9.0") == []


def test_doc_title_flags_stale_baseline(libdocsconsistency, tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text("# Upgrade guide: PodiumD 4.8.2 → 4.9.0\n")
    issues = libdocsconsistency.check_doc_title(doc, "4.8.5", "4.9.0")
    assert len(issues) == 1
    assert "does not read" in issues[0]


def test_doc_title_handles_empty_file(libdocsconsistency, tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text("")
    issues = libdocsconsistency.check_doc_title(doc, "4.8.5", "4.9.0")
    assert len(issues) == 1


def test_check_companion_doc_missing_file(libdocsconsistency, tmp_path):
    name, issues = libdocsconsistency.check_companion_doc(tmp_path, "4.8.5", "4.9.0", "gemeente-specific")
    assert name == "4.8.5-to-4.9.0-gemeente-specific.md"
    assert "does not exist" in issues[0]


def test_check_companion_doc_existing_correct_file(libdocsconsistency, tmp_path):
    (tmp_path / "4.8.5-to-4.9.0-values-deltas.md").write_text(
        "# Values deltas — PodiumD 4.8.5 → 4.9.0\n\nNo changes.\n")
    name, issues = libdocsconsistency.check_companion_doc(tmp_path, "4.8.5", "4.9.0", "values-deltas")
    assert name == "4.8.5-to-4.9.0-values-deltas.md"
    assert issues == []


def test_check_baseline_doc_set_all_three_missing(libdocsconsistency, tmp_path):
    issues = libdocsconsistency.check_baseline_doc_set(tmp_path, "4.8.5", "4.9.0")
    assert len(issues) == 3
    assert all("does not exist" in i for i in issues)


def test_check_baseline_doc_set_all_present_and_valid(libdocsconsistency, tmp_path):
    for suffix, title in [
        ("upgrade", "Upgrade guide"),
        ("gemeente-specific", "Gemeente-specific notes"),
        ("values-deltas", "Values deltas"),
    ]:
        (tmp_path / f"4.8.5-to-4.9.0-{suffix}.md").write_text(
            f"# {title} — PodiumD 4.8.5 → 4.9.0\n\ncontent\n")
    assert libdocsconsistency.check_baseline_doc_set(tmp_path, "4.8.5", "4.9.0") == []


def test_check_baseline_doc_set_reports_malformed_doc(libdocsconsistency, tmp_path):
    (tmp_path / "4.8.5-to-4.9.0-upgrade.md").write_text("no heading here\n")
    (tmp_path / "4.8.5-to-4.9.0-gemeente-specific.md").write_text("# Title\n\ncontent\n")
    (tmp_path / "4.8.5-to-4.9.0-values-deltas.md").write_text("# Title\n\ncontent\n")
    issues = libdocsconsistency.check_baseline_doc_set(tmp_path, "4.8.5", "4.9.0")
    assert len(issues) == 1
    assert "level-1 heading" in issues[0]
