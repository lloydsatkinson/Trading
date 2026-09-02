from __future__ import annotations

from datetime import datetime

from .models import FeedHealth


class FeedHealthMonitor:
    def __init__(
        self,
        delayed_after_seconds: float = 15.0,
        stale_after_seconds: float = 90.0,
    ) -> None:
        if delayed_after_seconds < 0 or stale_after_seconds <= delayed_after_seconds:
            raise ValueError("feed health thresholds must satisfy 0 <= delayed < stale")
        self.delayed_after_seconds = float(delayed_after_seconds)
        self.stale_after_seconds = float(stale_after_seconds)
        self.state = FeedHealth.DISCONNECTED
        self.lag_seconds: float | None = None
        self._recovering = False
        self._fresh_seen_in_recovery = False

    def connect(self) -> None:
        self.state = FeedHealth.RECOVERING
        self._recovering = False
        self._fresh_seen_in_recovery = False

    def disconnect(self) -> None:
        self.state = FeedHealth.DISCONNECTED
        self._recovering = False
        self._fresh_seen_in_recovery = False

    def begin_recovery(self) -> None:
        self.state = FeedHealth.RECOVERING
        self._recovering = True
        self._fresh_seen_in_recovery = False

    def observe_event(self, event_ts: datetime, now: datetime) -> None:
        if event_ts.tzinfo is None or event_ts.utcoffset() is None:
            raise ValueError("event_ts must be timezone-aware")
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")

        lag = max(0.0, (now - event_ts).total_seconds())
        self.lag_seconds = lag

        if self._recovering:
            if lag <= self.stale_after_seconds:
                self._fresh_seen_in_recovery = True
                self.state = FeedHealth.RECOVERING
            else:
                self.state = FeedHealth.STALE
            return

        if lag <= self.delayed_after_seconds:
            self.state = FeedHealth.LIVE
        elif lag <= self.stale_after_seconds:
            self.state = FeedHealth.DELAYED
        else:
            self.state = FeedHealth.STALE

    def mark_recovered(self) -> None:
        if not self._recovering or not self._fresh_seen_in_recovery:
            raise RuntimeError("cannot mark recovered before a non-stale event is observed")
        self._recovering = False
        self.state = FeedHealth.LIVE
