from __future__ import annotations

from math import isfinite
from statistics import median
from typing import Any

from scanner.core.features import attach_session_vwap, bucket_float, bucket_time_of_day
from scanner.core.models import market_cap_bucket

from .clock import SessionClock
from .models import FeatureSnapshot
from .symbol_state import SymbolState


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


class FeatureEngine:
    def __init__(self, clock: SessionClock | None = None) -> None:
        self.clock = clock or SessionClock()

    def snapshot(self, state: SymbolState, context: dict[str, Any]) -> FeatureSnapshot:
        bars = state.bars_frame()
        if bars.empty:
            raise LookupError("cannot calculate features without bars")

        enriched = attach_session_vwap(bars)
        latest = enriched.iloc[-1]
        latest_bar = state.latest

        prior_close = _number(context.get("prior_close"))
        gap_pct = latest_bar.close / prior_close - 1.0 if prior_close and prior_close > 0 else None
        rvol = _number(context.get("opening_rvol"))

        prior_volumes = [float(value) for value in bars["volume"].iloc[:-1].tail(5).tolist()]
        volume_acceleration = None
        if len(prior_volumes) >= 2:
            baseline = median(prior_volumes)
            if baseline > 0:
                volume_acceleration = float(latest_bar.volume) / float(baseline)

        market_cap = _number(context.get("market_cap"))
        float_shares = _number(context.get("float_shares"))
        spread_pct = _number(context.get("spread_pct"))

        return FeatureSnapshot(
            symbol=state.symbol,
            timestamp=latest_bar.timestamp,
            session=self.clock.classify(latest_bar.timestamp),
            last_price=float(latest_bar.close),
            session_vwap=_number(latest.get("session_vwap")),
            hod=float(enriched["high"].max()),
            lod=float(enriched["low"].min()),
            gap_pct=gap_pct,
            rvol=rvol,
            volume_acceleration=volume_acceleration,
            spread_pct=spread_pct,
            catalyst_class=str(context.get("catalyst_class") or "UNKNOWN"),
            market_cap_bucket=market_cap_bucket(market_cap),
            float_bucket=bucket_float(float_shares),
            time_of_day_bucket=bucket_time_of_day(latest_bar.timestamp),
            context=dict(context),
        )
