"""values-deltas.md "## ..." section cleanup, plus gemeente-specific.md placeholder checks.

Sections are written by hand; these helpers only tidy the TODO stub and empty sections."""

import re

from lib.component_docs.baseline_doc_stubs import GEMEENTE_SPECIFIC_STUB_LINE
from lib.component_docs.baseline_doc_stubs import VALUES_DELTAS_STUB_TODO_LINE
from lib.component_docs.doc_lines import strip_standalone_placeholder_line
from lib.upgradedoc.sorting_and_ordering import HeadingBlock
from lib.upgradedoc.sorting_and_ordering import parse_values_delta_sections
from lib.upgradedoc.version_cells import strip_html_comments


def strip_stale_values_deltas_todo_stub(text: str):
    """Remove the stub's TODO line left in the opening, before the first real section.

    Only the line itself, when it is a paragraph of its own; the rest of the
    opening stays. Callers can use the `changed` flag alone as a check. A doc
    with no real section yet is left alone. Returns (new_text, changed)."""
    sections = parse_values_delta_sections(text)
    if not sections:
        return text, False

    lines = text.splitlines(keepends=True)
    if not strip_standalone_placeholder_line(lines, sections[0]["start"], VALUES_DELTAS_STUB_TODO_LINE):
        return text, False
    return "".join(lines), True


GEMEENTE_SECTION_HEADING_RE = re.compile(r"^##\s+\S.*$", re.MULTILINE)


def has_real_gemeente_specific_content(text: str):
    """True if gemeente-specific.md has a real "## ..." section outside HTML comments.

    The stub's example heading lives inside a "<!-- ... -->" block, hence
    scanning strip_html_comments' output."""
    return bool(GEMEENTE_SECTION_HEADING_RE.search(strip_html_comments(text)))


def has_stale_gemeente_specific_placeholder(text: str):
    """True if gemeente-specific.md still has its "_None recorded yet._" line next to a real section.

    Check-only: the content is human-authored, so nothing auto-fixes it."""
    if not has_real_gemeente_specific_content(text):
        return False
    return any(line.strip() == GEMEENTE_SPECIFIC_STUB_LINE.strip() for line in text.splitlines())


def has_blank_body(lines: list[str], section: HeadingBlock):
    """True if nothing but blank lines follows `section`'s heading."""
    return not "".join(lines[section["start"] + 1 : section["end"]]).strip()


def prune_empty_values_delta_sections(text: str) -> tuple[str, list[str]]:
    """Delete every "## ..." section with a blank body, with its trailing blank lines.

    Returns (new_text, removed_headings)."""
    lines = text.splitlines(keepends=True)
    sections = parse_values_delta_sections(text)
    removed_headings: list[str] = []
    for section in reversed(sections):
        if not has_blank_body(lines, section):
            continue
        start, end = section["start"], section["end"]
        while end < len(lines) and not lines[end].strip():
            end += 1
        del lines[start:end]
        removed_headings.append(section["heading"])
    return "".join(lines), list(reversed(removed_headings))
