from datetime import date, timedelta

import pytest

from scanner.core.validation import chronological_split, selectable_splits


def test_chronological_split_assigns_forward_only_after_locked_test():
    sessions = [date(2026, 1, 1) + timedelta(days=i) for i in range(8)]
    out = chronological_split(sessions, development_sessions=3, validation_sessions=2, test_sessions=2)
    assert [out[d] for d in sessions] == [
        "development", "development", "development",
        "validation", "validation",
        "test", "test", "forward",
    ]
    assert selectable_splits() == ("development", "validation")


def test_chronological_split_rejects_negative_lengths():
    with pytest.raises(ValueError):
        chronological_split([date(2026, 1, 1)], -1, 1, 1)


def test_chronological_split_preserves_input_order_requirement():
    sessions = [date(2026, 1, 2), date(2026, 1, 1)]
    with pytest.raises(ValueError):
        chronological_split(sessions, 1, 0, 0)
