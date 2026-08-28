from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class SerClickConfig:
    extension_ratio: float = 1.20
    pm_dollar_turnover_min: float = 10_000_000.0
    open30_dollar_turnover_min: float = 5_000_000.0

    min_prior_close: float = 1.00
    max_prior_close: float = 20.00

    shorts_building_drawdown: float = 0.10
    absorption_window_minutes: int = 10
    absorption_percentile: float = 0.80
    absorption_min_down_fraction: float = 0.50
    absorption_max_new_low_extension: float = 0.015
    absorption_min_down_dollar: float = 250_000.0
    absorption_memory_minutes: int = 60

    armed_distance_to_pain: float = 0.03

    expansion_window_minutes: int = 5
    expansion_percentile: float = 0.80
    expansion_min_up_displacement: float = 0.01
    expansion_min_buy_dollar: float = 50_000.0
    acceleration_min_return_3m: float = 0.005

    slippage_bps: float = 25.0
    mark_tolerance_minutes: int = 2
    forward_minutes: tuple[int, ...] = (5, 15, 30, 60, 120)

    development_sessions: int = 30
    validation_sessions: int = 15
    test_sessions: int = 15

    early_scan_timeframe: str = "30Min"
    minute_timeframe: str = "1Min"
    symbol_batch_size: int = 200
    api_limit: int = 10_000
    request_pause_seconds: float = 0.05

    def to_dict(self) -> dict:
        d = asdict(self)
        d["forward_minutes"] = list(self.forward_minutes)
        return d
