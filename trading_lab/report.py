from __future__ import annotations

from collections.abc import Iterable
import pandas as pd

from .metrics import ReturnMetrics, evaluate_returns
from .rules import RangeRule


def evaluate_strategy_splits(frame: pd.DataFrame, rule: RangeRule, *, roundtrip_cost: float = 0.005, splits: Iterable[str] = ("dev", "val", "hold", "final")) -> dict[str, ReturnMetrics]:
    mask = rule.mask(frame)
    out: dict[str, ReturnMetrics] = {}
    for split in splits:
        split_rows = frame[frame["split"].eq(split)]
        trading_days = max(1, split_rows["date"].nunique())
        returns = frame.loc[mask & frame["split"].eq(split), "return_1d"]
        out[split] = evaluate_returns(returns, roundtrip_cost, trading_days)
    return out
