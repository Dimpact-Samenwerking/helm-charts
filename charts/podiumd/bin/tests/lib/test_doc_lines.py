"""lib.component_docs.doc_lines: placeholder spans and the blank line before an inserted section."""

from lib.component_docs.doc_lines import is_bare_placeholder_span
from lib.component_docs.doc_lines import normalize_blank_line_before_insert


def test_is_bare_placeholder_span_only_placeholder_and_blanks():
    lines = ["# Title\n", "\n", "TODO: x\n", "\n"]
    assert is_bare_placeholder_span(lines, 1, len(lines), "TODO: x") is True


def test_is_bare_placeholder_span_false_with_other_text():
    lines = ["\n", "TODO: x\n", "Some prose.\n"]
    assert is_bare_placeholder_span(lines, 0, len(lines), "TODO: x") is False


def test_normalize_blank_line_before_insert_adds_missing_blank():
    lines = ["# Title\n", "text\n"]
    assert normalize_blank_line_before_insert(lines, 2) == 3
    assert lines == ["# Title\n", "text\n", "\n"]


def test_normalize_blank_line_before_insert_collapses_extra_blanks():
    lines = ["text\n", "\n", "\n", "\n", "## Next\n"]
    assert normalize_blank_line_before_insert(lines, 4) == 2
    assert lines == ["text\n", "\n", "## Next\n"]
