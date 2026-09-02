from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from typing import Any


class Direction(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"


class MarketSession(StrEnum):
    PREMARKET = "PREMARKET"
    REGULAR = "REGULAR"
    AFTER_HOURS = "AFTER_HOURS"
    CLOSED = "CLOSED"


class LifecycleState(StrEnum):
    DISCOVER = "DISCOVER"
    WATCH = "WATCH"
    ARMED = "ARMED"
    FIRE = "FIRE"
    MANAGE = "MANAGE"
    EXIT = "EXIT"
    INVALIDATED = "INVALIDATED"
    EXPIRED = "EXPIRED"
    DATA_DEGRADED = "DATA_DEGRADED"
    HALTED = "HALTED"


class ProductionStatus(StrEnum):
    RESEARCH = "RESEARCH"
    VALIDATION = "VALIDATION"
    LOCKED_TEST = "LOCKED_TEST"
    FORWARD_ONLY = "FORWARD_ONLY"
    PRODUCTION_ELIGIBLE = "PRODUCTION_ELIGIBLE"
    DISABLED = "DISABLED"


class FeedHealth(StrEnum):
    LIVE = "LIVE"
    DELAYED = "DELAYED"
    STALE = "STALE"
    DISCONNECTED = "DISCONNECTED"
    RECOVERING = "RECOVERING"


@dataclass(frozen=True)
class MarketBar:
    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class FeatureSnapshot:
    symbol: str
    timestamp: datetime
    session: MarketSession
    last_price: float
    session_vwap: float | None = None
    hod: float | None = None
    lod: float | None = None
    gap_pct: float | None = None
    rvol: float | None = None
    volume_acceleration: float | None = None
    spread_pct: float | None = None
    catalyst_class: str = "UNKNOWN"
    market_cap_bucket: str = "UNKNOWN"
    float_bucket: str = "UNKNOWN"
    time_of_day_bucket: str = "UNKNOWN"
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StrategyDescriptor:
    strategy_id: str
    strategy_family: str
    variant_id: str
    direction: Direction
    strategy_version: str
    production_status: ProductionStatus
    production_eligible: bool
    correlation_group: str
    evidence_score: float
    required_features: tuple[str, ...] = ()


@dataclass(frozen=True)
class StrategyIntent:
    descriptor: StrategyDescriptor
    symbol: str
    state: LifecycleState
    event_timestamp: datetime
    setup_anchor: datetime
    reference_price: float
    setup_score: float
    execution_score: float
    reason_codes: tuple[str, ...]
    explanation: str
    entry_trigger: float | None = None
    stop_reference: float | None = None
    target_1: float | None = None
    target_2: float | None = None
    management_policy: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LiveSignalEvent:
    event_id: str
    signal_id: str
    intent: StrategyIntent
    effective_state: LifecycleState
    action_label: str
    feed_health: FeedHealth
    source_timestamp: datetime


def stable_signal_id(
    strategy_id: str,
    variant_id: str,
    symbol: str,
    direction: Direction | str,
    setup_anchor: datetime,
    strategy_version: str,
) -> str:
    raw = "|".join(
        (
            strategy_id,
            variant_id,
            symbol.upper(),
            str(direction),
            setup_anchor.isoformat(),
            strategy_version,
        )
    )
    return sha256(raw.encode("utf-8")).hexdigest()[:24]


def stable_event_id(
    signal_id: str,
    state: LifecycleState | str,
    event_timestamp: datetime,
) -> str:
    raw = "|".join((signal_id, str(state), event_timestamp.isoformat()))
    return sha256(raw.encode("utf-8")).hexdigest()[:24]
