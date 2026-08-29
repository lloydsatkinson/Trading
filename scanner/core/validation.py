from __future__ import annotations

from collections.abc import Sequence
from datetime import date


def selectable_splits() -> tuple[str, ...]:
    return ("development", "validation")


def chronological_split(
    sessions: Sequence[date],
    development_sessions: int,
    validation_sessions: int,
    test_sessions: int,
) -> dict[date, str]:
    lengths = (development_sessions, validation_sessions, test_sessions)
    if any(v < 0 for v in lengths):
        raise ValueError("split lengths must be non-negative")
    ordered = list(sessions)
    if ordered != sorted(ordered):
        raise ValueError("sessions must be supplied in chronological order")

    development_end = development_sessions
    validation_end = development_end + validation_sessions
    test_end = validation_end + test_sessions
    out: dict[date, str] = {}
    for index, session in enumerate(ordered):
        if index < development_end:
            split = "development"
        elif index < validation_end:
            split = "validation"
        elif index < test_end:
            split = "test"
        else:
            split = "forward"
        out[session] = split
    return out
