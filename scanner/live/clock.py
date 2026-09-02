from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from .models import MarketSession

ET = ZoneInfo("America/New_York")


class SessionClock:
    def _et(self, timestamp: datetime) -> datetime:
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return timestamp.astimezone(ET)

    def classify(self, timestamp: datetime) -> MarketSession:
        local = self._et(timestamp)
        tod = local.time()
        if time(4, 0) <= tod < time(9, 30):
            return MarketSession.PREMARKET
        if time(9, 30) <= tod < time(16, 0):
            return MarketSession.REGULAR
        if time(16, 0) <= tod < time(20, 0):
            return MarketSession.AFTER_HOURS
        return MarketSession.CLOSED

    def is_operating(self, timestamp: datetime) -> bool:
        return self.classify(timestamp) is not MarketSession.CLOSED

    def session_date(self, timestamp: datetime) -> date:
        return self._et(timestamp).date()
