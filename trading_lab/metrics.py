from __future__ import annotations

from dataclasses import dataclass
import math
import pandas as pd


@dataclass(frozen=True)
class ReturnMetrics:
    n: int
    expectancy: float
    profit_factor: float
    win_rate: float
    trades_per_day: float


def evaluate_returns(returns: pd.Series, roundtrip_cost: float = 0.0, trading_days: int | None = None) -> ReturnMetrics:
    clean = pd.Series(returns, dtype="float64").dropna()
    adjusted = clean - float(roundtrip_cost)
    n = int(len(adjusted))
    if n == 0:
        return ReturnMetrics(0, 0.0, 0.0, 0.0, 0.0)
    gains = float(adjusted[adjusted > 0].sum())
    losses = float(-adjusted[adjusted < 0].sum())
    pf = math.inf if losses == 0.0 and gains > 0 else (0.0 if losses == 0.0 else gains / losses)
    days = trading_days if trading_days is not None else n
    return ReturnMetrics(n, float(adjusted.mean()), float(pf), float((adjusted > 0).mean()), float(n / days if days else 0.0))
