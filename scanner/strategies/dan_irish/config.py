from __future__ import annotations

from dataclasses import dataclass


IMPULSE_GRID = (0.15, 0.20, 0.30, 0.50, 0.75)
TURNOVER_GRID = (1_000_000.0, 3_000_000.0, 5_000_000.0, 10_000_000.0)
RETAINED_GAIN_GRID = (0.40, 0.50, 0.65, 0.80)
CONSOLIDATION_MINUTES_GRID = (10, 20, 30, 45, 60, 90)
PULLBACK_DEPTH_GRID = (0.10, 0.20, 0.30, 0.40, 0.50)
BREAKOUT_VOLUME_RATIO_GRID = (1.0, 1.5, 2.0)
SWING_HOLD_SESSIONS = (1, 2, 3, 4, 5, 7, 10)
SWING_STOP_PCTS = (0.05, 0.08, 0.10, 0.15, 0.20)
MAX_COMPRESSION_BASE_SESSIONS = 5
MIN_REQUIRED_FOLLOWUP_SESSIONS = MAX_COMPRESSION_BASE_SESSIONS + 1 + max(SWING_HOLD_SESSIONS)


@dataclass(frozen=True)
class DanConfig:
    min_reference_extension_pct: float = 0.15
    min_activity_dollar_turnover: float = 1_000_000.0
    min_retained_gain: float = 0.40
    min_consolidation_minutes: int = 10
    max_pullback_depth: float = 0.50
    min_breakout_volume_ratio: float = 1.0
    volume_lookback_bars: int = 5
    slippage_bps: float = 25.0
    followup_sessions: int = MIN_REQUIRED_FOLLOWUP_SESSIONS
