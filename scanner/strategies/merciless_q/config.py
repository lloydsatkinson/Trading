from dataclasses import dataclass


@dataclass(frozen=True)
class MercilessConfig:
    min_price: float = 0.50
    max_price: float = 30.00
    min_gap_pct: float = 0.10
    min_pm_dollar_turnover: float = 1_000_000.0
    min_opening_rvol: float = 2.0
    min_impulse_pct: float = 0.15
    min_impulse_velocity_pct_per_min: float = 0.01
    min_retained_gain: float = 0.55
    max_pullback_fraction: float = 0.45
    min_contraction_bars: int = 2
    max_contraction_bars: int = 12
    min_breakout_volume_ratio: float = 1.20
    max_upper_wick_ratio: float = 0.55
    min_clv: float = 0.55
    cooldown_bars: int = 3
    max_signals_per_symbol: int = 8
    slippage_bps: float = 25.0
    volume_lookback_bars: int = 3
