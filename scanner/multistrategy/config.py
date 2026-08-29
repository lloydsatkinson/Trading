from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MultiStrategyConfig:
    min_gap_pct: float = 0.05
    min_activity_dollar_turnover: float = 1_000_000.0
    min_price: float = 1.0
    max_price: float = 30.0
    opening_baseline_sessions: int = 20
    development_sessions: int = 30
    validation_sessions: int = 15
    test_sessions: int = 15
    symbol_batch_size: int = 200
    api_limit: int = 10_000
    request_pause_seconds: float = 0.05
    early_scan_timeframe: str = "30Min"
    minute_timeframe: str = "1Min"
    opening_history_timeframe: str = "5Min"
