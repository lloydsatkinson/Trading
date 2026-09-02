from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime
from typing import Any

from .consensus import build_consensus
from .feature_engine import FeatureEngine
from .feed_health import FeedHealthMonitor
from .forward_ledger import ForwardLedger
from .lifecycle import LifecycleEngine
from .models import (
    FeedHealth,
    FeatureSnapshot,
    LifecycleState,
    LiveSignalEvent,
    MarketBar,
    RankedOpportunity,
)
from .ranker import rank_active
from .signal_bus import SignalBus
from .strategy_registry import StrategyRegistry
from .symbol_state import SymbolStateStore


class ScannerService:
    def __init__(
        self,
        registry: StrategyRegistry,
        ledger: ForwardLedger,
        feature_engine: FeatureEngine | None = None,
        lifecycle: LifecycleEngine | None = None,
        feed_health: FeedHealthMonitor | None = None,
        signal_bus: SignalBus | None = None,
        restore_session_date: date | None = None,
    ) -> None:
        self.registry = registry
        self.ledger = ledger
        self.feature_engine = feature_engine or FeatureEngine()
        self.lifecycle = lifecycle or LifecycleEngine()
        self.feed_health = feed_health or FeedHealthMonitor()
        self.signal_bus = signal_bus or SignalBus()
        self.states = SymbolStateStore()
        self._latest_events: dict[str, LiveSignalEvent] = {}
        self._latest_by_adapter_symbol: dict[tuple[str, str, str, str], LiveSignalEvent] = {}
        self._features_by_symbol: dict[str, FeatureSnapshot] = {}
        self._ranked: list[RankedOpportunity] = []

        if restore_session_date is not None:
            self._restore(restore_session_date)

    @staticmethod
    def _adapter_key(adapter, symbol: str) -> tuple[str, str, str, str]:
        descriptor = adapter.descriptor
        return (
            descriptor.strategy_id,
            descriptor.variant_id,
            symbol.upper(),
            descriptor.direction.value,
        )

    @staticmethod
    def _event_key(event: LiveSignalEvent) -> tuple[str, str, str, str]:
        descriptor = event.intent.descriptor
        return (
            descriptor.strategy_id,
            descriptor.variant_id,
            event.intent.symbol.upper(),
            descriptor.direction.value,
        )

    def _restore(self, session_date: date) -> None:
        for event in self.ledger.latest_events(session_date):
            self.lifecycle.restore(event)
            self._latest_events[event.signal_id] = event
            self._latest_by_adapter_symbol[self._event_key(event)] = event

    def seed_bar(self, bar: MarketBar, context: dict[str, Any] | None = None) -> bool:
        state = self.states.get(bar.symbol)
        if state.has_timestamp(bar.timestamp):
            return False
        state.append_bar(bar)
        return True

    def process_bar(self, bar: MarketBar, context: dict[str, Any]) -> list[LiveSignalEvent]:
        state = self.states.get(bar.symbol)
        state.append_bar(bar)

        if self.feed_health.state is FeedHealth.DISCONNECTED:
            self.feed_health.connect()
        observed_at = context.get("_scanner_now", bar.timestamp)
        if not isinstance(observed_at, datetime):
            raise ValueError("_scanner_now must be a timezone-aware datetime")
        self.feed_health.observe_event(bar.timestamp, now=observed_at)
        self.ledger.append_health(
            bar.timestamp,
            self.feed_health.state,
            {"lag_seconds": self.feed_health.lag_seconds},
        )

        features = self.feature_engine.snapshot(state, context)
        self._features_by_symbol[bar.symbol.upper()] = features

        emitted: list[LiveSignalEvent] = []
        symbol_halted = bool(context.get("_symbol_halted", False))
        for adapter in self.registry.adapters:
            key = self._adapter_key(adapter, bar.symbol)
            prior_event = self._latest_by_adapter_symbol.get(key)
            intent = adapter.evaluate(state, features, prior_event)
            if intent is None:
                continue
            if (
                symbol_halted
                and intent.state is LifecycleState.FIRE
                and intent.descriptor.production_eligible
            ):
                intent = replace(
                    intent,
                    state=LifecycleState.HALTED,
                    reason_codes=tuple((*intent.reason_codes, "SYMBOL_HALTED")),
                    explanation=f"{intent.explanation}; production FIRE blocked by trading halt",
                )
            event = self.lifecycle.apply(intent, self.feed_health.state)
            if event is None:
                continue

            self.ledger.append_event(event, features)
            self.signal_bus.publish(event)
            self._latest_events[event.signal_id] = event
            self._latest_by_adapter_symbol[key] = event
            emitted.append(event)

        active = list(self._latest_events.values())
        consensus = build_consensus(active)
        self._ranked = rank_active(active, self._features_by_symbol, consensus)
        return emitted

    def active_events(self) -> list[LiveSignalEvent]:
        return list(self._latest_events.values())

    def ranked_snapshot(self) -> list[RankedOpportunity]:
        return list(self._ranked)
