from __future__ import annotations

import pandas as pd

from scanner.strategies.orb_stocks_in_play.config import ORBConfig
from scanner.strategies.orb_stocks_in_play.strategy import detect_orb_triggers

from ..models import Direction, FeatureSnapshot, LifecycleState, StrategyDescriptor, StrategyIntent
from ..symbol_state import SymbolState


class ORBLiveAdapter:
    def __init__(self, descriptor: StrategyDescriptor, cfg: ORBConfig | None = None) -> None:
        self.descriptor = descriptor
        self.cfg = cfg or ORBConfig()

    def evaluate(self, state: SymbolState, features: FeatureSnapshot, prior_event) -> StrategyIntent | None:
        latest_ts = pd.Timestamp(state.latest.timestamp)
        for decision in detect_orb_triggers(state.bars_frame(), features.context, self.cfg):
            if decision.variant_id != self.descriptor.variant_id:
                continue
            if decision.direction != self.descriptor.direction.value:
                continue
            if pd.Timestamp(decision.signal_timestamp) != latest_ts:
                continue
            event_ts = pd.Timestamp(decision.signal_timestamp).to_pydatetime()
            return StrategyIntent(
                descriptor=self.descriptor,
                symbol=state.symbol,
                state=LifecycleState.FIRE,
                event_timestamp=event_ts,
                setup_anchor=event_ts,
                reference_price=float(decision.reference_price),
                setup_score=50.0,
                execution_score=50.0,
                reason_codes=(decision.variant_id,),
                explanation="ORB shared trigger detected on completed bar",
                entry_trigger=float(decision.reference_price),
                stop_reference=decision.stop_reference,
                metadata={"setup_metadata": decision.setup_metadata},
            )
        return None
