from __future__ import annotations

from .rules import RangeRule


def candidate_strategies() -> list[RangeRule]:
    return [
        RangeRule(name="CATALYST_EARLY_RUNNER", min_price=1.0, max_price=20.0, move_1d=(0.05, 0.15), rvol=(2.0, 10.0), max_daily_rank=25, require_fresh_sec_days=3),
        RangeRule(name="CATALYST_ROBUST_3_12", min_price=1.0, max_price=20.0, move_1d=(0.03, 0.12), rvol=(2.0, 10.0), min_dollar_volume=250_000, max_daily_rank=25, require_fresh_sec_days=3),
        RangeRule(name="CATALYST_HF_6_15", min_price=1.0, max_price=20.0, move_1d=(0.06, 0.15), rvol=(1.5, 10.0), min_dollar_volume=250_000, max_daily_rank=30, require_fresh_sec_days=3),
        RangeRule(name="RUNNER_CONT_HF", min_price=1.0, max_price=20.0, move_1d=(0.05, 0.15), rvol=(20.0, 50.0)),
        RangeRule(name="HV_SHALLOW_PULLBACK", min_price=1.0, max_price=50.0, move_1d=(-0.05, 0.0), rvol=(10.0, 50.0)),
    ]
