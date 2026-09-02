from dataclasses import FrozenInstanceError
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from scanner.live.clock import SessionClock
from scanner.live.models import Direction, LifecycleState, MarketBar, MarketSession, stable_event_id, stable_signal_id

ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")


def test_market_bar_is_frozen_and_ids_are_deterministic():
    ts = datetime(2026, 9, 2, 9, 35, tzinfo=ET)
    bar = MarketBar("ABC", ts, 4.0, 4.3, 3.9, 4.2, 100_000)
    with pytest.raises(FrozenInstanceError):
        bar.close = 9.0

    first = stable_signal_id("ORB", "ORB_LONG_BREAK", "ABC", Direction.LONG, ts, "orb-v1")
    second = stable_signal_id("ORB", "ORB_LONG_BREAK", "ABC", Direction.LONG, ts, "orb-v1")
    assert first == second
    assert stable_event_id(first, LifecycleState.FIRE, ts) == stable_event_id(first, LifecycleState.FIRE, ts)


def test_session_clock_classifies_market_windows_and_converts_utc():
    clock = SessionClock()
    assert clock.classify(datetime(2026, 9, 2, 8, 0, tzinfo=ET)) is MarketSession.PREMARKET
    assert clock.classify(datetime(2026, 9, 2, 10, 0, tzinfo=ET)) is MarketSession.REGULAR
    assert clock.classify(datetime(2026, 9, 2, 17, 0, tzinfo=ET)) is MarketSession.AFTER_HOURS
    assert clock.classify(datetime(2026, 9, 2, 21, 0, tzinfo=ET)) is MarketSession.CLOSED
    assert clock.classify(datetime(2026, 9, 2, 13, 35, tzinfo=UTC)) is MarketSession.REGULAR


def test_session_clock_rejects_naive_datetimes():
    with pytest.raises(ValueError):
        SessionClock().classify(datetime(2026, 9, 2, 10, 0))
