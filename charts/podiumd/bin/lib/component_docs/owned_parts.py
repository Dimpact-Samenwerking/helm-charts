"""Rewrite or remove only the generated ("owned") lines of a doc section; user lines stay as they are.

A recogniser labels each line of a section with the kind of generated part
it belongs to (e.g. "intro", "bullet"), or None for a user line. Blank lines
are layout and get BLANK. The heading (line 0) is handled by the caller.
"""

import re

from collections.abc import Callable
from collections.abc import Mapping
from collections.abc import Sequence
from dataclasses import dataclass

from lib.upgradedoc.sorting_and_ordering import HeadingBlock

BLANK = "blank"

# A generated heading: "<name> <version transition>[ (chart ...)]", as version_transition /
# component_version_cell and the chart suffixes write it.
_GENERATED_HEADING_RE = re.compile(
    r"^(?P<name>.+?) (?:\S+ → \S+|\S+ \((?:new|unchanged|digest changed|removed)\))(?: \(chart [^)]*\))?$"
)


def _template_pattern(template: str, field_patterns: Mapping[str, str]) -> str:
    parts = re.split(r"\{(\w+)\}", template)
    # re.split with one group alternates literal text (even index) and field names.
    pieces: list[str] = []
    for index, part in enumerate(parts):
        pieces.append(re.escape(part) if index % 2 == 0 else field_patterns[part])
    return "".join(pieces)


def template_re(template: str, field_patterns: Mapping[str, str]) -> re.Pattern[str]:
    """A full-line regex for `template`, each {field} matched by field_patterns[field]."""
    return re.compile(f"{_template_pattern(template, field_patterns)}$")


def template_prefix_re(template: str, field_patterns: Mapping[str, str]) -> re.Pattern[str]:
    """A regex for a line that starts as `template` does, without its final punctuation, and may go on."""
    return re.compile(_template_pattern(template.rstrip(".:,"), field_patterns))


def generated_heading_name(heading: str, *other_shapes: re.Pattern[str]) -> str | None:
    """The "name" group of the first generated shape `heading` matches (version shape first), else None."""
    for shape in (_GENERATED_HEADING_RE, *other_shapes):
        shape_match = shape.match(heading)
        if shape_match:
            return shape_match.group("name")
    return None


def has_user_lines(kinds: Sequence[str | None]) -> bool:
    """Whether a labelled body holds any user line."""
    return any(kind is None for kind in kinds)


def _grouped(lines: Sequence[str], kinds: Sequence[str | None]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for line, kind in zip(lines, kinds, strict=True):
        if kind is not None and kind != BLANK:
            groups.setdefault(kind, []).append(line)
    return groups


def _collapse_blank_runs(lines: list[str]) -> list[str]:
    out: list[str] = []
    for line in lines:
        if not line.strip() and out and not out[-1].strip():
            continue
        out.append(line)
    return out


def _anchors(old_kinds: Sequence[str | None], order: list[str], *, absent_first: bool) -> dict[str, int]:
    """Old-body index each new kind is written at: its first old line, else just before the next kind that has one.

    With no such next kind: the end of the body, or with `absent_first` its first non-blank line."""
    first: dict[str, int] = {}
    for line_index, kind in enumerate(old_kinds):
        if kind is not None and kind != BLANK:
            first.setdefault(kind, line_index)
    anchors: dict[str, int] = {}
    following = len(old_kinds)
    if absent_first:
        following = next((line_index for line_index, kind in enumerate(old_kinds) if kind != BLANK), following)
    for kind in reversed(order):
        following = first.get(kind, following)
        anchors[kind] = following
    return anchors


def replace_owned_parts(
    old_body: Sequence[str],
    old_kinds: Sequence[str | None],
    new_body: Sequence[str],
    new_kinds: Sequence[str | None],
    *,
    absent_first: bool = False,
) -> list[str]:
    """`old_body` with its owned lines replaced by `new_body`'s, user lines kept in place and in order.

    Each kind of `new_body` goes where that kind was in `old_body`; a kind
    `old_body` lacks goes before the next kind that it has (see _anchors for
    `absent_first`), and an owned kind `new_body` lacks is dropped.
    """
    new_groups = _grouped(new_body, new_kinds)
    anchors = _anchors(old_kinds, list(new_groups), absent_first=absent_first)
    old_groups = set(_grouped(old_body, old_kinds))
    out: list[str] = []
    for position in range(len(old_body) + 1):
        for kind, group in new_groups.items():
            if anchors[kind] != position:
                continue
            if kind in old_groups:
                out.extend(group)  # the old blank lines around it stay as they were
            else:
                gap = ["\n"] if out and out[-1].strip() else []
                out.extend([*gap, *group, "\n"])
        if position < len(old_body) and old_kinds[position] in {None, BLANK}:
            out.append(old_body[position])
    return _collapse_blank_runs(out)


def remove_owned_parts(body: Sequence[str], kinds: Sequence[str | None]) -> list[str]:
    """`body` without its owned lines; user lines and the blank lines between them stay."""
    kept = [line for line, kind in zip(body, kinds, strict=True) if kind is None or kind == BLANK]
    return _collapse_blank_runs(kept)


# Labels a section body (the lines after its heading) line by line.
BodyKinds = Callable[[Sequence[str]], list[str | None]]
# The component a generated heading line names (None: hand-written), given its body's kinds.
HeadingName = Callable[[str, Sequence[str | None]], str | None]
# A heading line and its body's kinds.
type HeadingWithKinds = tuple[str, Sequence[str | None]]


@dataclass(frozen=True)
class SectionShape:
    """How one doc's sections are labelled: body_kinds, heading_name and the edited-line prefixes.

    With absent_first, an owned kind the old body lacks goes before its user
    lines instead of after them (see _anchors)."""

    body_kinds: BodyKinds
    heading_name: HeadingName
    absent_first: bool = False
    # template_prefix_re of the generated lines, for edited_generated_lines; a
    # continuation ("to 1.3.") counts only right after a generated line.
    edited_openers: Sequence[re.Pattern[str]] = ()
    edited_continuations: Sequence[re.Pattern[str]] = ()


def _with_section_gap(body: list[str], *, followed: bool) -> list[str]:
    """`body` without trailing blank lines, plus one when another line follows the section."""
    while body and not body[-1].strip():
        body = body[:-1]
    return [*body, "\n"] if followed else body


def _kept_or_new_heading(old: HeadingWithKinds, new: HeadingWithKinds, heading_name: HeadingName) -> str:
    """The new heading line when the old one is generated for the same component, else the old one."""
    old_name = heading_name(*old)
    return new[0] if old_name is not None and old_name == heading_name(*new) else old[0]


def replace_section_owned_parts(text: str, block: HeadingBlock, section_text: str, shape: SectionShape) -> str:
    """`block` with its owned parts replaced by `section_text`'s; user lines stay in place.

    The heading is replaced only when it is generated and names the same
    component as the new one; a hand-written heading is kept.
    """
    lines = text.splitlines(keepends=True)
    start, end = block["start"], block["end"]
    new_lines = section_text.splitlines(keepends=True)
    old_body, new_body = lines[start + 1 : end], new_lines[1:]
    old_kinds, new_kinds = shape.body_kinds(old_body), shape.body_kinds(new_body)
    heading = _kept_or_new_heading((lines[start], old_kinds), (new_lines[0], new_kinds), shape.heading_name)
    body = replace_owned_parts(old_body, old_kinds, new_body, new_kinds, absent_first=shape.absent_first)
    section = [heading, *_with_section_gap(body, followed=end < len(lines))]
    return "".join([*lines[:start], *section, *lines[end:]])


def remove_section_owned_parts(text: str, block: HeadingBlock | None, shape: SectionShape) -> tuple[str, bool, bool]:
    """Remove `block`'s owned parts: (new_text, removed, kept_user_text).

    A block without user lines is deleted with its trailing blank lines; one
    with user lines keeps its heading and those lines. (text, False, False) if
    block is None.
    """
    if block is None:
        return text, False, False
    lines = text.splitlines(keepends=True)
    start, end = block["start"], block["end"]
    body = lines[start + 1 : end]
    kinds = shape.body_kinds(body)
    if has_user_lines(kinds):
        kept = _with_section_gap(remove_owned_parts(body, kinds), followed=end < len(lines))
        new_text = "".join([*lines[: start + 1], *kept, *lines[end:]])
        return new_text, True, True
    while end < len(lines) and not lines[end].strip():
        end += 1
    del lines[start:end]
    return "".join(lines), True, False


def edited_generated_lines(text: str, blocks: Sequence[HeadingBlock], shape: SectionShape) -> list[tuple[str, str]]:
    """(heading, line) for each user line in `blocks` that starts like a generated line but goes on.

    Such a line is usually a generated line edited by hand. The writers no
    longer own it, so it stays next to the rewritten line and can go stale.
    """
    lines = text.splitlines(keepends=True)
    found: list[tuple[str, str]] = []
    for block in blocks:
        body = lines[block["start"] + 1 : block["end"]]
        after_owned = False
        for line, kind in zip(body, shape.body_kinds(body), strict=True):
            text_line = line.rstrip("\n")
            prefixes = [*shape.edited_openers, *(shape.edited_continuations if after_owned else ())]
            if kind is None and any(prefix.match(text_line) for prefix in prefixes):
                found.append((block["heading"], text_line))
            after_owned = kind not in {None, BLANK}
    return found
