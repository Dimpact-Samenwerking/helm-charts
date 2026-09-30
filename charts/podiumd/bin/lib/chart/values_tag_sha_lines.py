"""Line-level editing of a split "tag:" + sibling "sha:"/"digest:" pin, preserving comments and anchors."""

import re

from dataclasses import dataclass

from lib.chart.values_tree_primitives import replace_scalar_value


def find_block_end(lines: list[str], block_start: int, indent: int) -> int:
    """The exclusive end index of the block starting at block_start (a key
    line at `indent`): the next non-blank, non-comment line at indent <=
    that level, or EOF."""
    for i in range(block_start + 1, len(lines)):
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if len(line) - len(line.lstrip(" ")) <= indent:
            return i
    return len(lines)


def find_child_key_line(lines: list[str], key: str, parent_indent: int, block_start: int, block_end: int) -> int | None:
    """The "<key>:" line directly under the block in [block_start, block_end), ignoring deeper same-named keys."""
    key_re = re.compile(rf"^(\s*){re.escape(key)}:\s*(.*)$")
    candidates: list[tuple[int, int]] = []
    child_indents: list[int] = []
    for i in range(block_start, block_end):
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        if indent > parent_indent:
            child_indents.append(indent)
        m = key_re.match(line)
        if m and len(m.group(1)) > parent_indent:
            candidates.append((len(m.group(1)), i))
    if not candidates:
        return None
    child_level = min(child_indents)
    return next((i for indent, i in candidates if indent == child_level), None)


def locate_dotted_key_line(lines: list[str], dotted_path: str) -> tuple[int, int] | None:
    """Walk a dotted path (e.g. "zac.opa.image.tag") down through nested
    mapping blocks, returning (line_index, indent) of the final key, or None
    if any segment can't be found unambiguously."""
    located = locate_parent_block(lines, dotted_path)
    if located is None:
        return None
    indent, body_start, _body_end = located
    # The final key's own line is the one right before its body.
    return body_start - 1, indent


def locate_parent_block(lines: list[str], dotted_path: str) -> tuple[int, int, int] | None:
    """(indent, start, end) of the final segment's body, for looking up several sibling keys."""
    segments = dotted_path.split(".")
    indent, start, end = -1, 0, len(lines)
    for seg in segments:
        idx = find_child_key_line(lines, seg, indent, start, end)
        if idx is None:
            return None
        indent = len(lines[idx]) - len(lines[idx].lstrip(" "))
        start = idx + 1
        end = find_block_end(lines, idx, indent)
    return indent, start, end


# A bare alias ("<key>: *anchor"); write_tag_and_sha skips it since the anchor's own site is written.
ALIAS_REFERENCE_RE = re.compile(r"^\s*\S+:\s*\*\w+\s*(#.*)?\s*$")


def is_alias_reference_line(line: str) -> bool:
    """Whether `line` is a bare YAML alias reference rather than a literal value."""
    return bool(ALIAS_REFERENCE_RE.match(line))


def locate_tag_and_sha(
    lines: list[str], values_key: str, path: str, sibling_field: str
) -> tuple[int, int, int | None] | None:
    """(tag_line_index, tag_indent, sibling_line_index_or_None) at values_key.path, or None without "tag:".

    sibling_line_index is None when podiumd doesn't override it yet.
    """
    located = locate_parent_block(lines, f"{values_key}.{path}")
    if located is None:
        return None
    parent_indent, start, end = located
    tag_idx = find_child_key_line(lines, "tag", parent_indent, start, end)
    if tag_idx is None:
        return None
    tag_indent = len(lines[tag_idx]) - len(lines[tag_idx].lstrip(" "))
    sibling_idx = find_child_key_line(lines, sibling_field, parent_indent, start, end)
    return tag_idx, tag_indent, sibling_idx


@dataclass
class SiblingWrite:
    """write_tag_and_sha's values, bundled to avoid too-many-arguments."""

    new_version: str
    new_digest_hex: str
    sibling_field: str
    label: str


def write_tag_and_sha(lines: list[str], location: tuple[int, int, int | None], write: SiblingWrite) -> bool:
    """Write the new tag and digest into `lines` at `location`, inserting the sibling line if missing.

    A bare alias line is skipped with a note. Returns whether the tag line
    was written.
    """
    tag_line_index, tag_indent, sibling_line_index = location
    sibling_value = f"sha256:{write.new_digest_hex}" if write.sibling_field == "digest" else write.new_digest_hex
    tag_written = not is_alias_reference_line(lines[tag_line_index])
    if not tag_written:
        print(f"  {write.label}.tag: *alias reference — inherits from its own anchor, not written directly")
    else:
        lines[tag_line_index] = replace_scalar_value(lines[tag_line_index], write.new_version)
    if sibling_line_index is not None:
        if is_alias_reference_line(lines[sibling_line_index]):
            print(
                f"  {write.label}.{write.sibling_field}: *alias reference — "
                "inherits from its own anchor, not written directly"
            )
        else:
            lines[sibling_line_index] = replace_scalar_value(lines[sibling_line_index], sibling_value)
    else:
        indent_str = " " * tag_indent
        lines.insert(tag_line_index + 1, f'{indent_str}{write.sibling_field}: "{sibling_value}"\n')
    return tag_written
