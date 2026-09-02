from __future__ import annotations

from .models import (
    FeedHealth,
    LifecycleState,
    LiveSignalEvent,
    StrategyIntent,
    stable_event_id,
    stable_signal_id,
)


_ALLOWED: dict[LifecycleState, set[LifecycleState]] = {
    LifecycleState.DISCOVER: {
        LifecycleState.WATCH,
        LifecycleState.ARMED,
        LifecycleState.INVALIDATED,
        LifecycleState.EXPIRED,
    },
    LifecycleState.WATCH: {
        LifecycleState.ARMED,
        LifecycleState.INVALIDATED,
        LifecycleState.EXPIRED,
        LifecycleState.DATA_DEGRADED,
        LifecycleState.HALTED,
    },
    LifecycleState.ARMED: {
        LifecycleState.FIRE,
        LifecycleState.INVALIDATED,
        LifecycleState.EXPIRED,
        LifecycleState.DATA_DEGRADED,
        LifecycleState.HALTED,
    },
    LifecycleState.FIRE: {
        LifecycleState.MANAGE,
        LifecycleState.EXIT,
        LifecycleState.INVALIDATED,
        LifecycleState.DATA_DEGRADED,
        LifecycleState.HALTED,
    },
    LifecycleState.MANAGE: {
        LifecycleState.EXIT,
        LifecycleState.INVALIDATED,
        LifecycleState.DATA_DEGRADED,
        LifecycleState.HALTED,
    },
    LifecycleState.DATA_DEGRADED: {
        LifecycleState.WATCH,
        LifecycleState.ARMED,
        LifecycleState.INVALIDATED,
        LifecycleState.EXPIRED,
    },
    LifecycleState.HALTED: {
        LifecycleState.WATCH,
        LifecycleState.ARMED,
        LifecycleState.INVALIDATED,
        LifecycleState.EXPIRED,
    },
    LifecycleState.EXIT: set(),
    LifecycleState.INVALIDATED: set(),
    LifecycleState.EXPIRED: set(),
}

_BLOCKING_FEED_STATES = {
    FeedHealth.STALE,
    FeedHealth.DISCONNECTED,
    FeedHealth.RECOVERING,
}


def _action_label(intent: StrategyIntent, effective_state: LifecycleState) -> str:
    direction = intent.descriptor.direction.value
    if effective_state is LifecycleState.FIRE:
        if intent.descriptor.production_eligible:
            return f"FIRE {direction}"
        return "RESEARCH FIRE"
    if effective_state is LifecycleState.ARMED:
        return f"ARMED {direction}"
    if effective_state is LifecycleState.DATA_DEGRADED:
        return "DATA DEGRADED"
    if effective_state is LifecycleState.WATCH:
        return "WATCH"
    if effective_state is LifecycleState.INVALIDATED:
        return "INVALIDATED"
    if effective_state is LifecycleState.EXPIRED:
        return "EXPIRED"
    if effective_state is LifecycleState.HALTED:
        return "HALTED"
    if effective_state is LifecycleState.MANAGE:
        return "MANAGE"
    if effective_state is LifecycleState.EXIT:
        return "EXIT"
    return "DISCOVER"


class LifecycleEngine:
    def __init__(self) -> None:
        self._latest_by_signal: dict[str, LiveSignalEvent] = {}

    def _signal_id(self, intent: StrategyIntent) -> str:
        d = intent.descriptor
        return stable_signal_id(
            d.strategy_id,
            d.variant_id,
            intent.symbol,
            d.direction,
            intent.setup_anchor,
            d.strategy_version,
        )

    def prior_event(self, intent: StrategyIntent) -> LiveSignalEvent | None:
        return self._latest_by_signal.get(self._signal_id(intent))

    def restore(self, event: LiveSignalEvent) -> None:
        self._latest_by_signal[event.signal_id] = event

    def apply(self, intent: StrategyIntent, feed_health: FeedHealth) -> LiveSignalEvent | None:
        signal_id = self._signal_id(intent)
        prior = self._latest_by_signal.get(signal_id)

        effective_state = intent.state
        if (
            intent.state is LifecycleState.FIRE
            and intent.descriptor.production_eligible
            and feed_health in _BLOCKING_FEED_STATES
        ):
            effective_state = LifecycleState.DATA_DEGRADED

        if prior is not None:
            if effective_state is prior.effective_state:
                return None
            if effective_state not in _ALLOWED.get(prior.effective_state, set()):
                raise ValueError(
                    f"illegal lifecycle transition {prior.effective_state.value} -> {effective_state.value}"
                )

        event = LiveSignalEvent(
            event_id=stable_event_id(signal_id, effective_state, intent.event_timestamp),
            signal_id=signal_id,
            intent=intent,
            effective_state=effective_state,
            action_label=_action_label(intent, effective_state),
            feed_health=feed_health,
            source_timestamp=intent.event_timestamp,
        )
        self._latest_by_signal[signal_id] = event
        return event
