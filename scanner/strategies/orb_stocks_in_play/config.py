from __future__ import annotations

from dataclasses import dataclass


GAP_GRID = (0.05, 0.08, 0.10, 0.15, 0.20)
PM_TURNOVER_GRID = (1_000_000.0, 2_000_000.0, 5_000_000.0, 10_000_000.0)
OPENING_RVOL_GRID = (3.0, 5.0, 10.0)
BREAKOUT_VOLUME_RATIO_GRID = (1.5, 2.0, 3.0)
CLV_GRID = (0.60, 0.75)


@dataclass(frozen=True)
class ORBConfig:
    min_gap_pct: float = 0.05
    min_pm_dollar_turnover: float = 1_000_000.0
    min_opening_rvol: float = 3.0
    min_breakout_volume_ratio: float = 1.5
    min_clv: float = 0.60
    min_price: float = 1.0
    max_price: float = 30.0
    opening_range_minutes: int = 5
    volume_lookback_bars: int = 5
    pullback_tolerance_pct: float = 0.01
    slippage_bps: float = 25.0
