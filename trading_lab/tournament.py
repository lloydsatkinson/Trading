from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping
import pandas as pd

from .metrics import ReturnMetrics, evaluate_returns
from .rules import RangeRule


@dataclass(frozen=True)
class TournamentConfig:
    roundtrip_cost: float = 0.005
    minimum_n: Mapping[str, int] | None = None

    def mins(self) -> Mapping[str, int]:
        return self.minimum_n or {"dev": 100, "val": 30, "hold": 12}


@dataclass(frozen=True)
class FrozenEvaluation:
    rule: RangeRule
    final: ReturnMetrics
    accepted: bool
    reason: str


def _metrics_for_split(frame: pd.DataFrame, rule: RangeRule, split: str, cost: float) -> ReturnMetrics:
    scoped = frame[(frame["split"] == split) & rule.mask(frame)]
    trading_days = max(1, frame.loc[frame["split"] == split, "date"].nunique())
    return evaluate_returns(scoped["return_1d"], cost, trading_days)


def rank_candidates(frame: pd.DataFrame, rules: Iterable[RangeRule], cfg: TournamentConfig) -> pd.DataFrame:
    rows = []
    mins = cfg.mins()
    for rule in rules:
        by_split = {s: _metrics_for_split(frame, rule, s, cfg.roundtrip_cost) for s in ("dev", "val", "hold")}
        if any(by_split[s].n < mins.get(s, 0) for s in by_split):
            continue
        if any(by_split[s].expectancy <= 0 or by_split[s].profit_factor <= 1.0 for s in by_split):
            continue
        row = {"name": rule.name}
        for split, m in by_split.items():
            row.update({f"{split}_n": m.n, f"{split}_expectancy": m.expectancy, f"{split}_profit_factor": m.profit_factor, f"{split}_trades_per_day": m.trades_per_day})
        row["min_profit_factor"] = min(m.profit_factor for m in by_split.values())
        row["min_expectancy"] = min(m.expectancy for m in by_split.values())
        rows.append(row)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(["min_profit_factor", "min_expectancy"], ascending=False).reset_index(drop=True)


def evaluate_frozen_candidate(frame: pd.DataFrame, rule: RangeRule, *, roundtrip_cost: float = 0.005, minimum_final_n: int = 20, min_final_pf: float = 1.3) -> FrozenEvaluation:
    final = _metrics_for_split(frame, rule, "final", roundtrip_cost)
    if final.n < minimum_final_n:
        return FrozenEvaluation(rule, final, False, "FINAL_SAMPLE_TOO_SMALL")
    if final.expectancy <= 0:
        return FrozenEvaluation(rule, final, False, "FINAL_EXPECTANCY_NON_POSITIVE")
    if final.profit_factor < min_final_pf:
        return FrozenEvaluation(rule, final, False, "FINAL_PROFIT_FACTOR_TOO_LOW")
    return FrozenEvaluation(rule, final, True, "ACCEPTED")
