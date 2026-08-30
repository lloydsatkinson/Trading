from __future__ import annotations

from typing import Iterable

import pandas as pd

from scanner.core.peak import PeakResult, analyze_same_session_peak as _shared_peak
from scanner.core.replay import ReplayResult, ReplayRule, replay_signal_grid as _shared_replay_signal_grid, simulate_trade
from scanner.core.rules import MAX_HOLD_MINUTES


def analyze_same_session_peak(
    bars: pd.DataFrame,
    entry_price: float,
    entry_timestamp,
) -> PeakResult:
    return _shared_peak(bars, entry_price, entry_timestamp, "LONG", session_end="20:00")


def simulate_long_trade(
    bars: pd.DataFrame,
    entry_price: float,
    entry_timestamp,
    rule: ReplayRule,
) -> ReplayResult:
    return simulate_trade(bars, entry_price, entry_timestamp, "LONG", rule, session_end="20:00")


def default_rule_grid() -> list[ReplayRule]:
    return [
        ReplayRule(stop_pct=s, target_pct=t, max_hold_minutes=h)
        for s in (0.03, 0.05, 0.07, 0.10, 0.15, 0.20, 0.30, 0.40, 0.50)
        for t in (0.05, 0.10, 0.15, 0.20, 0.30)
        for h in MAX_HOLD_MINUTES
    ]


def replay_signal_grid(
    bars: pd.DataFrame,
    signal: dict | pd.Series,
    rules: Iterable[ReplayRule] | None = None,
) -> pd.DataFrame:
    signal_dict = signal.to_dict() if isinstance(signal, pd.Series) else dict(signal)
    signal_dict.setdefault("direction", "LONG")
    peak = analyze_same_session_peak(
        bars,
        float(signal_dict["entry_price_slipped"]),
        signal_dict["entry_timestamp"],
    )
    out = _shared_replay_signal_grid(
        bars,
        signal_dict,
        list(rules or default_rule_grid()),
        session_end="20:00",
    )
    if not out.empty:
        for key, value in peak.to_dict().items():
            out[key] = value
    return out
