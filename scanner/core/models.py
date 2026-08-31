from __future__ import annotations

from dataclasses import asdict, dataclass, field
from math import isfinite
from typing import Any


def _finite_number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def market_cap_in_primary_universe(value: Any) -> bool:
    cap = _finite_number(value)
    return bool(cap is not None and 50_000_000 <= cap < 2_000_000_000)


def market_cap_bucket(value: Any) -> str:
    cap = _finite_number(value)
    if cap is None:
        return "UNKNOWN"
    if cap < 50_000_000:
        return "BELOW_MICROCAP"
    if cap < 300_000_000:
        return "MICROCAP"
    if cap < 2_000_000_000:
        return "SMALL_CAP"
    return "LARGER"


def price_bucket(value: Any) -> str:
    price = _finite_number(value)
    if price is None or price <= 0:
        return "UNKNOWN"
    if price < 1:
        return "LT_1"
    if price < 2:
        return "1_2"
    if price < 5:
        return "2_5"
    if price < 10:
        return "5_10"
    if price < 20:
        return "10_20"
    if price < 50:
        return "20_50"
    if price < 100:
        return "50_100"
    return "GE_100"


@dataclass(frozen=True)
class SignalRecord:
    strategy_id: str
    variant_id: str
    symbol: str
    date: str
    direction: str
    signal_timestamp: Any
    reference_price: float
    entry_timestamp: Any
    entry_price_raw: float
    entry_price_slipped: float
    stop_reference: float | None = None
    market_cap: float | None = None
    market_cap_bucket: str = "UNKNOWN"
    float_shares: float | None = None
    float_bucket: str = "UNKNOWN"
    gap_bucket: str = "UNKNOWN"
    rvol_bucket: str = "UNKNOWN"
    time_of_day_bucket: str = "UNKNOWN"
    catalyst_class: str = "UNKNOWN"
    borrow_status: str = "UNKNOWN"
    setup_metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
