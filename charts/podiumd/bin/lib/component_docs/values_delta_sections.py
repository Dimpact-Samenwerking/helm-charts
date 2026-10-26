"""values-deltas.md "## ..." section cleanup, plus gemeente-specific.md placeholder checks.

Sections are written by hand; these helpers only tidy the TODO stub and empty sections."""

import re

from lib.component_docs.baseline_doc_stubs import GEMEENTE_SPECIFIC_STUB_LINE
from lib.component_docs.baseline_doc_stubs import VALUES_DELTAS_STUB_TODO_LINE
from lib.component_docs.doc_lines import is_bare_placeholder_span
from lib.upgradedoc.sorting_and_ordering import HeadingBlock
from lib.upgradedoc.sorting_and_ordering import parse_values_delta_sections
from lib.upgradedoc.version_cells import strip_html_comments


def _is_bare_values_deltas_todo_stub(lines: list[str]):
    """True if `lines` is exactly the values-deltas stub: an H1 title plus VALUES_DELTAS_STUB_TODO_LINE."""
    title_idx = next((i for i, line in enumerate(lines) if line.strip()), None)
    return (
        title_idx is not None
        and lines[title_idx].strip().startswith("# ")
        and is_bare_placeholder_span(lines, title_idx + 1, len(lines), VALUES_DELTAS_STUB_TODO_LINE)
    )


def strip_stale_values_deltas_todo_stub(text: str):
    """Remove the TODO stub line left between the H1 title and the first real section.

    Callers can use the `changed` flag alone as a check. A doc with no real
    section yet is left alone. Returns (new_text, changed)."""
    sections = parse_values_delta_sections(text)
    if not sections:
        return text, False

    lines = text.splitlines(keepends=True)
    first_section_start = sections[0]["start"]
    prefix = lines[:first_section_start]
    if not _is_bare_values_deltas_todo_stub(prefix):
        return text, False

    title_line = next(line for line in prefix if line.strip())
    return title_line + "\n" + "".join(lines[first_section_start:]), True


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
