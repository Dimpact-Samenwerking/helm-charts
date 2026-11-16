"""Spans of a text's lines between consecutive start lines."""

from collections.abc import Sequence


def consecutive_spans(starts: Sequence[int], end: int, gap: int = 0) -> list[tuple[int, int]]:
    """(start, end) per start: each span ends `gap` lines before the next start.

    The last span ends at `end`; [] without starts.
    """
    ends = [next_start - gap for next_start in starts[1:]]
    return list(zip(starts, [*ends, end], strict=True)) if starts else []
