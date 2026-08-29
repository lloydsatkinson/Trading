from __future__ import annotations

from dataclasses import dataclass


GAP_GRID = (0.05, 0.10, 0.15, 0.20)
IMPULSE_GRID = (0.10, 0.15, 0.20, 0.30)
PM_TURNOVER_GRID = (2_000_000.0, 5_000_000.0, 10_000_000.0)
RVOL_GRID = (3.0, 5.0, 10.0)
RETAINED_GAIN_GRID = (0.40, 0.60, 0.70, 0.80)
RECLAIM_VOLUME_RATIO_GRID = (1.5, 2.0, 3.0)


@dataclass(frozen=True)
class VWAPConfig:
    min_gap_pct: float = 0.05
    min_impulse_pct: float = 0.10
    min_rvol: float = 3.0
    min_pm_dollar_turnover: float = 2_000_000.0
    min_retained_gain: float = 0.60
    min_reclaim_volume_ratio: float = 1.5
    min_clv: float = 0.50
    min_price: float = 1.0
    max_price: float = 30.0
    volume_lookback_bars: int = 5
    slippage_bps: float = 25.0
