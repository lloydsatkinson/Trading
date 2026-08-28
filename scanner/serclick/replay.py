from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Iterable

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class ReplayRule:
    stop_pct: float
    target_pct: float
    max_hold_minutes: int

    @property
    def rule_id(self) -> str:
        s = int(round(self.stop_pct * 100))
        t = int(round(self.target_pct * 100))
        return f"S{s:02d}_T{t:02d}_H{self.max_hold_minutes}"


@dataclass(frozen=True)
class ReplayResult:
    exit_reason: str
    exit_timestamp: pd.Timestamp | None
    exit_price: float
    return_pct: float
    bars_held: int

    def to_dict(self) -> dict:
        return asdict(self)


def _ensure_et_timestamp(value) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize("America/New_York")
    return ts.tz_convert("America/New_York")


def simulate_long_trade(
    bars: pd.DataFrame,
    entry_price: float,
    entry_timestamp,
    rule: ReplayRule,
) -> ReplayResult:
    """Replay one long trade using conservative minute-bar ordering.

    If stop and target are both touched in the same minute, the stop is assumed
    first. This deliberately avoids optimistic intrabar ordering assumptions.
    """
    if bars.empty or not np.isfinite(entry_price) or entry_price <= 0:
        return ReplayResult("NO_DATA", None, np.nan, np.nan, 0)

    x = bars.copy()
    if "timestamp_et" not in x.columns:
        if "timestamp" not in x.columns:
            raise ValueError("bars must contain timestamp_et or timestamp")
        x["timestamp_et"] = pd.to_datetime(x["timestamp"], utc=True).dt.tz_convert("America/New_York")
    else:
        x["timestamp_et"] = pd.to_datetime(x["timestamp_et"], utc=True).dt.tz_convert("America/New_York")

    entry_ts = _ensure_et_timestamp(entry_timestamp)
    end_ts = entry_ts + pd.Timedelta(minutes=rule.max_hold_minutes)
    x = x[(x["timestamp_et"] >= entry_ts) & (x["timestamp_et"] <= end_ts)].sort_values("timestamp_et")
    if x.empty:
        return ReplayResult("NO_DATA", None, np.nan, np.nan, 0)

    stop_price = entry_price * (1.0 - rule.stop_pct)
    target_price = entry_price * (1.0 + rule.target_pct)

    for bars_held, row in enumerate(x.itertuples(index=False), start=1):
        low = float(row.low)
        high = float(row.high)
        ts = row.timestamp_et
        stop_hit = low <= stop_price
        target_hit = high >= target_price
        if stop_hit and target_hit:
            return ReplayResult("STOP_SAME_BAR", ts, stop_price, -rule.stop_pct, bars_held)
        if stop_hit:
            return ReplayResult("STOP", ts, stop_price, -rule.stop_pct, bars_held)
        if target_hit:
            return ReplayResult("TARGET", ts, target_price, rule.target_pct, bars_held)

    last = x.iloc[-1]
    exit_price = float(last["close"])
    ret = exit_price / entry_price - 1.0
    return ReplayResult("TIME", last["timestamp_et"], exit_price, ret, len(x))


def default_rule_grid() -> list[ReplayRule]:
    return [
        ReplayRule(stop_pct=s, target_pct=t, max_hold_minutes=h)
        for s in (0.03, 0.05, 0.07, 0.10)
        for t in (0.05, 0.10, 0.15, 0.20, 0.30)
        for h in (30, 60, 120)
    ]


def replay_signal_grid(
    bars: pd.DataFrame,
    signal: dict | pd.Series,
    rules: Iterable[ReplayRule] | None = None,
) -> pd.DataFrame:
    rules = list(rules or default_rule_grid())
    entry_price = float(signal["entry_price_slipped"])
    entry_ts = signal["entry_timestamp"]
    rows = []
    for rule in rules:
        result = simulate_long_trade(bars, entry_price, entry_ts, rule)
        row = {
            "symbol": signal.get("symbol"),
            "date": signal.get("date"),
            "split": signal.get("split"),
            "population": signal.get("population"),
            "ignition_window": signal.get("ignition_window"),
            "rule_id": rule.rule_id,
            "stop_pct": rule.stop_pct,
            "target_pct": rule.target_pct,
            "max_hold_minutes": rule.max_hold_minutes,
            **result.to_dict(),
        }
        rows.append(row)
    return pd.DataFrame(rows)
