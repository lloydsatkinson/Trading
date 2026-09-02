from __future__ import annotations

import numpy as np
import pandas as pd

from scanner.core.features import bucket_time_of_day
from scanner.serclick.config import SerClickConfig
from scanner.serclick.features import analyze_candidate_day
from scanner.strategies.serclick_leo.strategy import serclick_variant

from ..models import FeatureSnapshot, LifecycleState, StrategyDescriptor, StrategyIntent
from ..symbol_state import SymbolState


_STATE_MAP = {
    "SHORTS_BUILDING": LifecycleState.WATCH,
    "ABSORPTION": LifecycleState.WATCH,
    "ARMED": LifecycleState.ARMED,
    "IGNITION": LifecycleState.FIRE,
}


def _analysis_frame(state: SymbolState) -> pd.DataFrame:
    frame = state.bars_frame().copy()
    if frame.empty:
        return frame
    frame["timestamp"] = pd.to_datetime(frame["timestamp_et"], utc=True)
    frame["vwap"] = np.nan
    frame["trade_count"] = 0
    return frame[["symbol", "timestamp", "open", "high", "low", "close", "volume", "trade_count", "vwap"]]


class SerClickLeoLiveAdapter:
    def __init__(self, descriptor: StrategyDescriptor, cfg: SerClickConfig | None = None) -> None:
        self.descriptor = descriptor
        self.cfg = cfg or SerClickConfig()

    def evaluate(self, state: SymbolState, features: FeatureSnapshot, prior_event) -> StrategyIntent | None:
        frame = _analysis_frame(state)
        if frame.empty:
            return None

        qualification = dict(features.context)
        transitions, _ = analyze_candidate_day(frame, qualification, self.cfg)
        if transitions.empty:
            return None

        latest_ts = pd.Timestamp(state.latest.timestamp)
        transition_ts = pd.to_datetime(transitions["timestamp"], utc=True, errors="coerce").dt.tz_convert("America/New_York")
        current = transitions.loc[transition_ts.eq(latest_ts)].copy()
        if current.empty:
            return None

        source = current.iloc[-1]
        mapped_state = _STATE_MAP.get(str(source.get("state")))
        if mapped_state is None:
            return None

        population = str(qualification.get("population") or "UNKNOWN")
        variant = serclick_variant(population, bucket_time_of_day(latest_ts))
        if variant != self.descriptor.variant_id:
            return None

        discovered = transitions[transitions["state"].astype(str).eq("DISCOVERED")]
        if discovered.empty:
            setup_anchor = latest_ts.to_pydatetime()
        else:
            setup_anchor = pd.Timestamp(discovered.iloc[0]["timestamp"]).to_pydatetime()

        metadata = {
            "transition_state": str(source.get("state")),
            "transition_reason": str(source.get("reason") or ""),
            "population": population,
            "window": bucket_time_of_day(latest_ts),
        }
        for key in ("pain_level", "absorption_percentile", "expansion_percentile", "session_vwap", "fade_vwap"):
            value = source.get(key)
            if value is not None and pd.notna(value):
                metadata[key] = float(value)

        return StrategyIntent(
            descriptor=self.descriptor,
            symbol=state.symbol,
            state=mapped_state,
            event_timestamp=latest_ts.to_pydatetime(),
            setup_anchor=setup_anchor,
            reference_price=float(state.latest.close),
            setup_score=50.0,
            execution_score=50.0,
            reason_codes=(f"SERCLICK_{source.get('state')}",),
            explanation="SerClick state transition observed from causal prefix analysis",
            entry_trigger=float(state.latest.close) if mapped_state is LifecycleState.FIRE else None,
            stop_reference=None,
            metadata=metadata,
        )
