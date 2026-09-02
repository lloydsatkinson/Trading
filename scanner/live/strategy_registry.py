from __future__ import annotations

from dataclasses import replace
from typing import Protocol, runtime_checkable

import pandas as pd

from .models import FeatureSnapshot, ProductionStatus, StrategyDescriptor, StrategyIntent
from .symbol_state import SymbolState


@runtime_checkable
class LiveStrategyAdapter(Protocol):
    @property
    def descriptor(self) -> StrategyDescriptor: ...

    def evaluate(
        self,
        state: SymbolState,
        features: FeatureSnapshot,
        prior_event,
    ) -> StrategyIntent | None: ...


class _EvidenceBoundAdapter:
    def __init__(self, adapter: LiveStrategyAdapter, descriptor: StrategyDescriptor) -> None:
        self._adapter = adapter
        self.descriptor = descriptor

    def evaluate(self, state: SymbolState, features: FeatureSnapshot, prior_event):
        intent = self._adapter.evaluate(state, features, prior_event)
        if intent is None:
            return None
        if intent.descriptor != self.descriptor:
            intent = replace(intent, descriptor=self.descriptor)
        return intent


class StrategyRegistry:
    def __init__(self, adapters) -> None:
        self.adapters = tuple(adapters)

    @classmethod
    def from_leaderboard(cls, adapters, leaderboard: pd.DataFrame) -> "StrategyRegistry":
        bound = []
        leaderboard = leaderboard.copy() if leaderboard is not None else pd.DataFrame()

        for adapter in adapters:
            source = adapter.descriptor
            row = None
            if not leaderboard.empty and {"strategy_id", "variant_id", "direction"}.issubset(leaderboard.columns):
                matches = leaderboard[
                    leaderboard["strategy_id"].astype(str).eq(source.strategy_id)
                    & leaderboard["variant_id"].astype(str).eq(source.variant_id)
                    & leaderboard["direction"].astype(str).str.upper().eq(source.direction.value)
                ]
                if not matches.empty:
                    row = matches.iloc[0]

            eligible = bool(row.get("production_eligible", False)) if row is not None else False
            robustness = 0.0
            if row is not None:
                try:
                    robustness = float(row.get("robustness_score", 0.0))
                except (TypeError, ValueError):
                    robustness = 0.0
                if not pd.notna(robustness):
                    robustness = 0.0
            evidence_score = max(0.0, min(100.0, robustness * 100.0))

            descriptor = replace(
                source,
                production_eligible=eligible,
                production_status=(
                    ProductionStatus.PRODUCTION_ELIGIBLE if eligible else ProductionStatus.RESEARCH
                ),
                evidence_score=evidence_score,
            )
            bound.append(_EvidenceBoundAdapter(adapter, descriptor))

        return cls(bound)
