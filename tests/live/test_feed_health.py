from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from scanner.live.feed_health import FeedHealthMonitor
from scanner.live.models import FeedHealth

ET = ZoneInfo("America/New_York")


def test_feed_health_tracks_lag_and_requires_explicit_recovery():
    now = datetime(2026, 9, 2, 10, 0, tzinfo=ET)
    health = FeedHealthMonitor(delayed_after_seconds=15.0, stale_after_seconds=90.0)

    health.connect()
    assert health.state is FeedHealth.RECOVERING

    health.observe_event(now - timedelta(seconds=20), now=now)
    assert health.state is FeedHealth.DELAYED

    health.observe_event(now - timedelta(seconds=100), now=now)
    assert health.state is FeedHealth.STALE

    health.begin_recovery()
    with pytest.raises(RuntimeError):
        health.mark_recovered()

    health.observe_event(now, now=now)
    assert health.state is FeedHealth.RECOVERING
    health.mark_recovered()
    assert health.state is FeedHealth.LIVE


def test_disconnect_sets_disconnected_state():
    health = FeedHealthMonitor()
    health.disconnect()
    assert health.state is FeedHealth.DISCONNECTED
