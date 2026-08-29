from __future__ import annotations

from typing import Iterable

import pandas as pd

from scanner.core.replay import ReplayResult, ReplayRule, replay_signal_grid as _shared_replay_signal_grid, simulate_trade


def simulate_long_trade(
    bars: pd.DataFrame,
    entry_price: float,
    entry_timestamp,
    rule: ReplayRule,
) -> ReplayResult:
    return simulate_trade(bars, entry_price, entry_timestamp, "LONG", rule)


def default_rule_grid() -> list[ReplayRule]:
    return [
        ReplayRule(stop_pct=s, target_pct=t, max_hold_minutes=h)
        for s in (0.03, 0.05, 0.07, 0.10, 0.15, 0.20, 0.30, 0.40, 0.50)
        for t in (0.05, 0.10, 0.15, 0.20, 0.30)
        for h in (30, 60, 120)
    ]


def replay_signal_grid(
    bars: pd.DataFrame,
    signal: dict | pd.Series,
    rules: Iterable[ReplayRule] | None = None,
) -> pd.DataFrame:
    signal_dict = signal.to_dict() if isinstance(signal, pd.Series) else dict(signal)
    signal_dict.setdefault("direction", "LONG")
    return _shared_replay_signal_grid(bars, signal_dict, list(rules or default_rule_grid()))
