"""Line-list helpers shared by the upgrade.md and values-deltas.md section writers."""


def is_bare_placeholder_span(lines: list[str], start: int, end: int, placeholder_text: str):
    """True if lines[start:end] holds only blank lines and exactly one line
    equal to placeholder_text (stripped). Exact match on purpose: human
    prose mentioning the placeholder must never be deleted."""
    non_blank = [line.strip() for line in lines[start:end] if line.strip()]
    return non_blank == [placeholder_text.strip()]


def normalize_blank_line_before_insert(lines: list[str], insert_at: int):
    """Ensure exactly one blank line before insert_at, returning the shifted
    index. Section text starts with a heading and the preceding trailing blank
    may already be gone (EOF collapsing), which would break MD022/MD032."""
    blank_count = 0
    i = insert_at - 1
    while i >= 0 and not lines[i].strip():
        blank_count += 1
        i -= 1
    if blank_count == 0:
        lines[insert_at:insert_at] = ["\n"]
        insert_at += 1
    elif blank_count > 1:
        del lines[insert_at - (blank_count - 1) : insert_at]
        insert_at -= blank_count - 1
    return insert_at
