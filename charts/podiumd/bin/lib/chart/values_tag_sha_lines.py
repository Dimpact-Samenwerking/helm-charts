"""Line-level editing of a split "tag:" + sibling "sha:"/"digest:" image
pin in values.yaml text, keeping comments, anchors and formatting
intact. update-component-version writes these for the digest_pinning.
exceptions entries marked writable (see lib.settings.
digest_pinning_exceptions)."""

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
    """The immediate child "<key>:" line inside [block_start, block_end) —
    matched only at the block's own immediate-child indent level, so a
    same-named key nested deeper under a sibling sub-block is never
    mistaken for a direct child that doesn't actually exist."""
    key_re = re.compile(rf"^(\s*){re.escape(key)}:\s*(.*)$")
    candidates = []
    child_indents = []
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
    if not candidates or not child_indents:
        return None
    child_level = min(child_indents)
    at_child_level = [i for indent, i in candidates if indent == child_level]
    return at_child_level[0] if at_child_level else None


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
    """Like locate_dotted_key_line, but stops one level higher: returns
    (indent, start, end) for the FINAL segment's own body, so a caller
    can look for more than one sibling key within it."""
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


# A bare YAML alias reference — "<key>: *someAnchor" — that write_tag_
# and_sha must skip (real case: keycloak.image's "tag:"/"sha:" are bare
# aliases of keycloak-operator...keycloakImage's own anchor; the anchor's
# own site is written for real elsewhere, so the alias still inherits it).
ALIAS_REFERENCE_RE = re.compile(r"^\s*\S+:\s*\*\w+\s*(#.*)?\s*$")


def is_alias_reference_line(line: str) -> bool:
    """True if `line` is a bare YAML alias reference (see
    ALIAS_REFERENCE_RE) rather than a literal scalar value."""
    return bool(ALIAS_REFERENCE_RE.match(line))


def locate_tag_and_sha(
    lines: list[str], values_key: str, path: str, sibling_field: str
) -> tuple[int, int, int | None] | None:
    """(tag_line_index, tag_indent, sibling_line_index_or_None) for the
    "tag:"/"<sibling_field>:" pair at values_key.path. sibling_line_index
    is None when podiumd doesn't override it yet. None if "tag:" itself
    can't be found."""
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
    """New tag/sibling values + field name + print label, bundled for
    write_tag_and_sha (too-many-arguments)."""

    new_version: str
    new_digest_hex: str
    sibling_field: str
    label: str


def write_tag_and_sha(lines: list[str], location: tuple[int, int, int | None], write: SiblingWrite) -> bool:
    """Write write.new_version/new_digest_hex into the "tag:"/sibling-field
    lines at `location` (locate_tag_and_sha's own return value), inserting
    a sibling line if none exists. Either line is skipped instead, with a
    printed note, if it's a bare YAML alias reference. Mutates `lines`.
    Returns whether the tag line itself was written (False for a live
    alias, which keeps resolving to its anchor's value)."""
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
