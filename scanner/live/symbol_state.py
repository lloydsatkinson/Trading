from __future__ import annotations

from collections import deque
from zoneinfo import ZoneInfo

import pandas as pd

from .models import MarketBar

ET = ZoneInfo("America/New_York")


class SymbolState:
    def __init__(self, symbol: str, max_bars: int = 600) -> None:
        if max_bars <= 0:
            raise ValueError("max_bars must be positive")
        self.symbol = str(symbol).upper()
        self._bars: deque[MarketBar] = deque(maxlen=int(max_bars))

    @property
    def latest(self) -> MarketBar:
        if not self._bars:
            raise LookupError("symbol state has no bars")
        return self._bars[-1]

    def has_timestamp(self, timestamp) -> bool:
        return any(bar.timestamp == timestamp for bar in self._bars)

    def append_bar(self, bar: MarketBar) -> None:
        if bar.symbol.upper() != self.symbol:
            raise ValueError("bar symbol does not match state symbol")
        if bar.timestamp.tzinfo is None or bar.timestamp.utcoffset() is None:
            raise ValueError("bar timestamp must be timezone-aware")
        if self._bars and bar.timestamp <= self._bars[-1].timestamp:
            raise ValueError("bar timestamp must be strictly increasing")
        self._bars.append(bar)

    def bars_frame(self) -> pd.DataFrame:
        rows = []
        for bar in self._bars:
            timestamp_et = bar.timestamp.astimezone(ET)
            rows.append(
                {
                    "symbol": bar.symbol.upper(),
                    "timestamp_et": timestamp_et,
                    "session_date": timestamp_et.date(),
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume": bar.volume,
                }
            )
        if rows:
            return pd.DataFrame(rows)
        return pd.DataFrame(
            columns=[
                "symbol",
                "timestamp_et",
                "session_date",
                "open",
                "high",
                "low",
                "close",
                "volume",
            ]
        )


class SymbolStateStore:
    def __init__(self, max_bars: int = 600) -> None:
        self.max_bars = int(max_bars)
        self._states: dict[str, SymbolState] = {}

    def get(self, symbol: str) -> SymbolState:
        key = str(symbol).upper()
        if key not in self._states:
            self._states[key] = SymbolState(key, max_bars=self.max_bars)
        return self._states[key]
