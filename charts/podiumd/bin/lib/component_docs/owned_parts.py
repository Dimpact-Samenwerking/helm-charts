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
    r"^(?P<name>.+?) (?:\S+ → \S+|\S+ \((?:new|unchanged|digest changed)\))(?: \(chart [^)]*\))?$"
)


def template_re(template: str, field_patterns: Mapping[str, str]) -> re.Pattern[str]:
    """A full-line regex for `template`, each {field} matched by field_patterns[field]."""
    parts = re.split(r"\{(\w+)\}", template)
    return re.compile(
        "".join(re.escape(part) if i % 2 == 0 else field_patterns[part] for i, part in enumerate(parts)) + r"$"
    )


def generated_heading_name(heading: str, *other_shapes: re.Pattern[str]) -> str | None:
    """The "name" group of the first generated shape `heading` matches (version shape first), else None."""
    for shape in (_GENERATED_HEADING_RE, *other_shapes):
        m = shape.match(heading)
        if m:
            return m.group("name")
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
    for i, kind in enumerate(old_kinds):
        if kind is not None and kind != BLANK:
            first.setdefault(kind, i)
    anchors: dict[str, int] = {}
    following = len(old_kinds)
    if absent_first:
        following = next((i for i, kind in enumerate(old_kinds) if kind != BLANK), following)
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
    for i in range(len(old_body) + 1):
        for kind, group in new_groups.items():
            if anchors[kind] != i:
                continue
            if kind in old_groups:
                out.extend(group)  # the old blank lines around it stay as they were
            else:
                out.extend(["\n", *group, "\n"] if out and out[-1].strip() else [*group, "\n"])
        if i < len(old_body) and old_kinds[i] in (None, BLANK):
            out.append(old_body[i])
    return _collapse_blank_runs(out)


def remove_owned_parts(body: Sequence[str], kinds: Sequence[str | None]) -> list[str]:
    """`body` without its owned lines; user lines and the blank lines between them stay."""
    kept = [line for line, kind in zip(body, kinds, strict=True) if kind is None or kind == BLANK]
    return _collapse_blank_runs(kept)


# Labels a section body (the lines after its heading) line by line.
BodyKinds = Callable[[Sequence[str]], list[str | None]]
# The component a generated heading line names (None: hand-written), given its body's kinds.
HeadingName = Callable[[str, Sequence[str | None]], str | None]


@dataclass(frozen=True)
class SectionShape:
    """How one doc's sections are labelled: body_kinds and heading_name.

    With absent_first, an owned kind the old body lacks goes before its user
    lines instead of after them (see _anchors)."""

    body_kinds: BodyKinds
    heading_name: HeadingName
    absent_first: bool = False


def _with_section_gap(body: list[str], *, followed: bool) -> list[str]:
    """`body` without trailing blank lines, plus one when another line follows the section."""
    while body and not body[-1].strip():
        body = body[:-1]
    return [*body, "\n"] if followed else body


def _kept_or_new_heading(
    old: tuple[str, Sequence[str | None]], new: tuple[str, Sequence[str | None]], heading_name: HeadingName
) -> str:
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
    lines[start:end] = [heading, *_with_section_gap(body, followed=end < len(lines))]
    return "".join(lines)


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
        lines[start:end] = [lines[start], *kept]
        return "".join(lines), True, True
    while end < len(lines) and not lines[end].strip():
        end += 1
    del lines[start:end]
    return "".join(lines), True, False
