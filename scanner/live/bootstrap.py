from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable
from zoneinfo import ZoneInfo

import pandas as pd

from .models import MarketBar

ET = ZoneInfo("America/New_York")


def _chunks(items: list[str], size: int = 200) -> Iterable[list[str]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


class SessionBootstrap:
    def __init__(self, rest, feed: str = "sip") -> None:
        self.rest = rest
        self.feed = str(feed).lower()

    def _active_us_symbols(self) -> list[str]:
        assets = self.rest.assets(include_inactive=True)
        if assets.empty or "symbol" not in assets.columns:
            return []
        frame = assets.copy()
        if "status" in frame.columns:
            frame = frame[frame["status"].astype(str).str.lower().eq("active")]
        if "asset_class" in frame.columns:
            frame = frame[frame["asset_class"].astype(str).str.lower().eq("us_equity")]
        if "tradable" in frame.columns:
            frame = frame[frame["tradable"].fillna(False).astype(bool)]
        symbols = sorted({str(value).strip().upper() for value in frame["symbol"] if str(value).strip()})
        return symbols

    def load_prior_closes(self, session_date: date) -> dict[str, float]:
        symbols = self._active_us_symbols()
        if not symbols:
            return {}

        calendar_start = session_date - timedelta(days=14)
        calendar = self.rest.calendar(str(calendar_start), str(session_date))
        sessions: list[date] = []
        if not calendar.empty and "date" in calendar.columns:
            sessions = sorted(
                value
                for value in pd.to_datetime(calendar["date"], errors="coerce").dt.date.dropna().tolist()
                if value < session_date
            )
        if not sessions:
            return {}
        history_start = sessions[max(0, len(sessions) - 5)]
        start_dt = datetime.combine(history_start, time(0), ET).astimezone(timezone.utc)
        end_dt = datetime.combine(session_date, time(0), ET).astimezone(timezone.utc)

        parts: list[pd.DataFrame] = []
        for batch in _chunks(symbols, 200):
            frame = self.rest.stock_bars(
                batch,
                "1Day",
                start_dt,
                end_dt,
                feed=self.feed,
                adjustment="raw",
            )
            if frame is not None and not frame.empty:
                parts.append(frame)
        if not parts:
            return {}

        daily = pd.concat(parts, ignore_index=True)
        daily["timestamp"] = pd.to_datetime(daily["timestamp"], utc=True, errors="coerce")
        daily["close"] = pd.to_numeric(daily["close"], errors="coerce")
        daily = daily.dropna(subset=["symbol", "timestamp", "close"])
        daily["session_date"] = daily["timestamp"].dt.tz_convert(ET).dt.date
        daily = daily[(daily["session_date"] < session_date) & (daily["close"] > 0)]
        if daily.empty:
            return {}
        daily["symbol"] = daily["symbol"].astype(str).str.upper()
        latest = daily.sort_values(["symbol", "timestamp"]).groupby("symbol", as_index=False).tail(1)
        return {str(row.symbol): float(row.close) for row in latest.itertuples()}

    def prime_symbol(self, symbol: str, session_date: date, before_ts: datetime) -> list[MarketBar]:
        if before_ts.tzinfo is None or before_ts.utcoffset() is None:
            raise ValueError("before_ts must be timezone-aware")
        symbol = str(symbol).strip().upper()
        if not symbol:
            return []
        start_dt = datetime.combine(session_date, time(4), ET).astimezone(timezone.utc)
        frame = self.rest.stock_bars(
            [symbol],
            "1Min",
            start_dt,
            before_ts.astimezone(timezone.utc),
            feed=self.feed,
            adjustment="raw",
        )
        if frame is None or frame.empty:
            return []
        x = frame.copy()
        x["timestamp"] = pd.to_datetime(x["timestamp"], utc=True, errors="coerce")
        for column in ("open", "high", "low", "close", "volume"):
            x[column] = pd.to_numeric(x[column], errors="coerce")
        x = x.dropna(subset=["timestamp", "open", "high", "low", "close", "volume"])
        cutoff = pd.Timestamp(before_ts).tz_convert("UTC")
        x = x[x["timestamp"] < cutoff].sort_values("timestamp")
        return [
            MarketBar(
                symbol=symbol,
                timestamp=row.timestamp.to_pydatetime(),
                open=float(row.open),
                high=float(row.high),
                low=float(row.low),
                close=float(row.close),
                volume=float(row.volume),
            )
            for row in x.itertuples()
        ]
