"""lib.line_spans: spans between consecutive start lines."""

from lib.line_spans import consecutive_spans


def test_consecutive_spans_without_starts_is_empty():
    assert consecutive_spans([], 10) == []


def test_consecutive_spans_one_start_runs_to_end():
    assert consecutive_spans([3], 10) == [(3, 10)]


def test_consecutive_spans_each_span_stops_at_next_start():
    assert consecutive_spans([0, 4, 7], 10) == [(0, 4), (4, 7), (7, 10)]


def test_consecutive_spans_gap_stops_before_next_start():
    assert consecutive_spans([0, 4, 7], 10, gap=1) == [(0, 3), (4, 6), (7, 10)]
