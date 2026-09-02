# Unified Real-Time Scanner Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a complete API-free real-time scanner core that evaluates ORB, VWAP and SerClick/Leo from one shared point-in-time state, enforces research/production gating, manages signal lifecycle and consensus ranking, and persists every trigger-equivalent event idempotently to SQLite.

**Architecture:** Add a focused `scanner/live/` package above the existing research code. Live strategy adapters consume immutable point-in-time symbol state and reuse/refactor existing batch decision logic so parity is tested rather than assumed. A deterministic fake stream drives the complete path `events -> state -> features -> adapters -> lifecycle -> consensus/ranker -> ledger`; no network or broker routing is permitted in Phase 1.

**Tech Stack:** Python, standard-library `dataclasses`, `enum`, `hashlib`, `sqlite3`, `zoneinfo`; pandas; NumPy; pytest. No new UI framework or broker library in Phase 1.

**Spec:** `docs/superpowers/specs/2026-09-02-unified-realtime-scanner-v1-design.md`

## Global Constraints

- No live-order routing is introduced anywhere in Phase 1.
- Completed one-minute decisions are the default live decision clock.
- All timestamps are timezone-aware and normalized to `America/New_York` for session logic.
- The existing `rank_strategies(..., production_min_expectancy=0.05)` result remains authoritative for production eligibility; the live scanner must not define a second evidence hurdle.
- Research/validation/locked-test/forward-only strategies may emit measurement events but may not produce an unlabeled production `FIRE`.
- Feed state `STALE`, `DISCONNECTED` or ambiguous recovery state blocks new production `FIRE` transitions.
- Missing fundamentals/float/catalyst values remain explicit `UNKNOWN`; no silent imputation.
- Consensus is correlation-aware; variants in one correlation group must receive diminishing, not additive, voting weight.
- Opposite-direction strong signals surface `CONFLICT`; they are never silently averaged away.
- Every trigger-equivalent event is append-only/idempotent in the forward ledger.
- Existing research behavior and tests must remain green after each strategy refactor.
- No API credentials, broker secrets, cached market data or generated SQLite database is committed.

---

## File Structure Locked for Phase 1

Create:

```text
scanner/live/
├── __init__.py                 # public live-scanner exports only
├── models.py                   # immutable live enums/dataclasses + stable IDs
├── clock.py                    # ET session classification and operating window
├── feed_health.py              # feed-health state machine and lag rules
├── symbol_state.py             # bounded point-in-time bar/context state per symbol
├── feature_engine.py           # shared features calculated once per symbol/timestamp
├── strategy_registry.py        # adapter protocol + evidence/production registry
├── lifecycle.py                # legal transitions, research gating, de-duplication
├── signal_bus.py               # append-only transition fan-out
├── consensus.py                # correlation-aware family agreement/conflict
├── ranker.py                   # 0-100 live ranking formula
├── forward_ledger.py           # SQLite persistence and restart state
├── fake_stream.py              # deterministic API-free event source
└── service.py                  # orchestration only; no strategy rules

tests/live/
├── test_models_clock.py
├── test_feed_health.py
├── test_symbol_state_features.py
├── test_strategy_registry.py
├── test_lifecycle.py
├── test_consensus_ranker.py
├── test_forward_ledger.py
├── test_orb_live_parity.py
├── test_vwap_live_parity.py
├── test_serclick_live_parity.py
└── test_live_service_end_to_end.py
```

Modify only where required for parity:

```text
scanner/core/models.py
scanner/strategies/orb_stocks_in_play/strategy.py
scanner/strategies/vwap_momentum/strategy.py
scanner/strategies/serclick_leo/strategy.py
scanner/strategies/*/__init__.py
```

Do not move or rename the existing research packages in Phase 1.

---

### Task 1: Immutable live models, stable IDs, and ET session clock

**Files:**
- Create: `scanner/live/__init__.py`
- Create: `scanner/live/models.py`
- Create: `scanner/live/clock.py`
- Test: `tests/live/test_models_clock.py`

**Interfaces:**
- Produces enums: `Direction`, `MarketSession`, `LifecycleState`, `ProductionStatus`, `FeedHealth`.
- Produces dataclasses: `MarketBar`, `FeatureSnapshot`, `StrategyDescriptor`, `StrategyIntent`, `LiveSignalEvent`.
- Produces: `stable_signal_id(...) -> str`, `stable_event_id(...) -> str`.
- Produces: `SessionClock.classify(timestamp) -> MarketSession`, `SessionClock.is_operating(timestamp) -> bool`, `SessionClock.session_date(timestamp) -> date`.

- [ ] **Step 1: Write failing immutable-model and ID tests**

```python
from dataclasses import FrozenInstanceError
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from scanner.live.models import (
    Direction, LifecycleState, MarketBar, ProductionStatus,
    stable_event_id, stable_signal_id,
)

ET = ZoneInfo("America/New_York")


def test_market_bar_is_immutable_and_ids_are_stable():
    bar = MarketBar(
        symbol="ABC",
        timestamp=datetime(2026, 9, 2, 9, 35, tzinfo=ET),
        open=4.0, high=4.3, low=3.9, close=4.2, volume=100_000,
    )
    with pytest.raises(FrozenInstanceError):
        bar.close = 9.0

    signal_id = stable_signal_id(
        strategy_id="ORB",
        variant_id="ORB_LONG_BREAK",
        symbol="ABC",
        direction=Direction.LONG,
        setup_anchor=bar.timestamp,
        strategy_version="orb-v1",
    )
    assert signal_id == stable_signal_id(
        "ORB", "ORB_LONG_BREAK", "ABC", Direction.LONG, bar.timestamp, "orb-v1"
    )
    assert stable_event_id(signal_id, LifecycleState.FIRE, bar.timestamp) == stable_event_id(
        signal_id, LifecycleState.FIRE, bar.timestamp
    )
```

- [ ] **Step 2: Write failing ET session tests, including DST-safe classification**

```python
from datetime import datetime
from zoneinfo import ZoneInfo

from scanner.live.clock import SessionClock
from scanner.live.models import MarketSession

ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")


def test_session_clock_classifies_premarket_regular_afterhours():
    clock = SessionClock()
    assert clock.classify(datetime(2026, 9, 2, 8, 0, tzinfo=ET)) is MarketSession.PREMARKET
    assert clock.classify(datetime(2026, 9, 2, 10, 0, tzinfo=ET)) is MarketSession.REGULAR
    assert clock.classify(datetime(2026, 9, 2, 17, 0, tzinfo=ET)) is MarketSession.AFTER_HOURS
    assert clock.classify(datetime(2026, 9, 2, 21, 0, tzinfo=ET)) is MarketSession.CLOSED


def test_utc_input_is_converted_before_classification():
    clock = SessionClock()
    assert clock.classify(datetime(2026, 9, 2, 13, 35, tzinfo=UTC)) is MarketSession.REGULAR
```

- [ ] **Step 3: Run tests and confirm RED**

Run:

```bash
PYTHONPATH=. pytest -q tests/live/test_models_clock.py
```

Expected: collection/import failure because `scanner.live` does not exist.

- [ ] **Step 4: Implement minimal immutable models**

`scanner/live/models.py` must define these exact public fields:

```python
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


def stable_signal_id(strategy_id, variant_id, symbol, direction, setup_anchor, strategy_version) -> str:
    raw = "|".join((strategy_id, variant_id, symbol.upper(), str(direction), setup_anchor.isoformat(), strategy_version))
    return sha256(raw.encode("utf-8")).hexdigest()[:24]


def stable_event_id(signal_id, state, event_timestamp) -> str:
    raw = "|".join((signal_id, str(state), event_timestamp.isoformat()))
    return sha256(raw.encode("utf-8")).hexdigest()[:24]
```

- [ ] **Step 5: Implement `SessionClock`**

`SessionClock` must reject naive datetimes, convert aware timestamps to ET, classify `04:00-09:29:59` premarket, `09:30-15:59:59` regular, `16:00-19:59:59` after-hours, otherwise closed, and define `is_operating()` as session != `CLOSED`.

- [ ] **Step 6: Run tests and full core model regression**

```bash
PYTHONPATH=. pytest -q tests/live/test_models_clock.py tests/test_core_models.py
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add scanner/live tests/live/test_models_clock.py
git commit -m "feat: add live scanner models and session clock"
```

---

### Task 2: Feed-health state machine with hard production-FIRE blocking inputs

**Files:**
- Create: `scanner/live/feed_health.py`
- Test: `tests/live/test_feed_health.py`

**Interfaces:**
- Consumes: `FeedHealth`.
- Produces: `FeedHealthMonitor` with `connect()`, `observe_event(ts, now)`, `disconnect()`, `begin_recovery()`, `mark_recovered()`, `state`, `lag_seconds`.

- [ ] **Step 1: Write failing feed-health transition tests**

```python
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from scanner.live.feed_health import FeedHealthMonitor
from scanner.live.models import FeedHealth

ET = ZoneInfo("America/New_York")


def test_feed_health_becomes_stale_from_event_lag_and_recovers_explicitly():
    now = datetime(2026, 9, 2, 10, 0, tzinfo=ET)
    health = FeedHealthMonitor(stale_after_seconds=90.0, delayed_after_seconds=15.0)
    health.connect()
    assert health.state is FeedHealth.RECOVERING

    health.observe_event(now - timedelta(seconds=20), now=now)
    assert health.state is FeedHealth.DELAYED

    health.observe_event(now - timedelta(seconds=100), now=now)
    assert health.state is FeedHealth.STALE

    health.begin_recovery()
    health.observe_event(now, now=now)
    assert health.state is FeedHealth.RECOVERING
    health.mark_recovered()
    assert health.state is FeedHealth.LIVE
```

- [ ] **Step 2: Write failing disconnect test**

```python
def test_disconnect_is_terminal_until_connect_or_recovery():
    health = FeedHealthMonitor()
    health.disconnect()
    assert health.state is FeedHealth.DISCONNECTED
```

- [ ] **Step 3: Run RED**

```bash
PYTHONPATH=. pytest -q tests/live/test_feed_health.py
```

- [ ] **Step 4: Implement deterministic thresholds**

Rules:
- `lag <= delayed_after_seconds` -> `LIVE`, except while explicitly `RECOVERING`.
- `delayed_after_seconds < lag <= stale_after_seconds` -> `DELAYED`.
- `lag > stale_after_seconds` -> `STALE`.
- `disconnect()` -> `DISCONNECTED` immediately.
- `connect()` and `begin_recovery()` -> `RECOVERING`.
- `mark_recovered()` is permitted only after at least one non-stale event has been observed since recovery began; otherwise raise `RuntimeError`.

- [ ] **Step 5: Run tests**

```bash
PYTHONPATH=. pytest -q tests/live/test_feed_health.py
```

- [ ] **Step 6: Commit**

```bash
git add scanner/live/feed_health.py tests/live/test_feed_health.py
git commit -m "feat: add live feed health state machine"
```

---

### Task 3: Bounded symbol state and one-pass shared feature engine

**Files:**
- Create: `scanner/live/symbol_state.py`
- Create: `scanner/live/feature_engine.py`
- Test: `tests/live/test_symbol_state_features.py`

**Interfaces:**
- Consumes: `MarketBar`, `FeatureSnapshot`, `SessionClock`.
- Produces: `SymbolState.append_bar(bar)`, `SymbolState.bars_frame()`, `SymbolState.latest`, `SymbolStateStore.get(symbol)`.
- Produces: `FeatureEngine.snapshot(state, context) -> FeatureSnapshot`.

- [ ] **Step 1: Write failing bounded-state test**

```python
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from scanner.live.models import MarketBar
from scanner.live.symbol_state import SymbolState

ET = ZoneInfo("America/New_York")


def test_symbol_state_is_chronological_and_bounded():
    state = SymbolState("ABC", max_bars=3)
    start = datetime(2026, 9, 2, 9, 30, tzinfo=ET)
    for i in range(4):
        state.append_bar(MarketBar("ABC", start + timedelta(minutes=i), 4+i*.1, 4.2+i*.1, 3.9+i*.1, 4.1+i*.1, 1000+i))
    assert len(state.bars_frame()) == 3
    assert state.latest.timestamp == start + timedelta(minutes=3)
```

Also require `append_bar` to raise `ValueError` for a different symbol, a naive timestamp, or a timestamp older than/equal to the latest stored bar.

- [ ] **Step 2: Write failing feature test against known VWAP/HOD/LOD**

```python
from scanner.live.feature_engine import FeatureEngine


def test_feature_engine_uses_only_bars_present_in_state():
    state = make_three_bar_state()  # local test helper with 09:30-09:32 bars
    snap = FeatureEngine().snapshot(
        state,
        {
            "prior_close": 4.0,
            "opening_rvol": 8.0,
            "market_cap": 120_000_000,
            "float_shares": 8_000_000,
            "catalyst_class": "EARNINGS",
        },
    )
    assert snap.hod == max(state.bars_frame()["high"])
    assert snap.lod == min(state.bars_frame()["low"])
    assert snap.gap_pct is not None
    assert snap.rvol == 8.0
    assert snap.catalyst_class == "EARNINGS"
```

- [ ] **Step 3: Run RED**

```bash
PYTHONPATH=. pytest -q tests/live/test_symbol_state_features.py
```

- [ ] **Step 4: Implement `SymbolState` using a bounded deque**

Keep bars as immutable `MarketBar` objects. `bars_frame()` converts only the current prefix into columns compatible with existing research helpers: `symbol`, `timestamp_et`, `session_date`, `open`, `high`, `low`, `close`, `volume`.

- [ ] **Step 5: Implement `FeatureEngine` by reusing existing research helpers**

Use `scanner.core.features.attach_session_vwap`, `bucket_float`, `bucket_gap`, `bucket_rvol`, and `bucket_time_of_day` rather than reimplementing formulas. Compute current HOD/LOD and session VWAP from the prefix only. `opening_rvol` may come from point-in-time context in Phase 1; if missing, snapshot `rvol=None`, never fabricate it.

Define volume acceleration as:

```python
latest_volume / median(previous up to 5 completed one-minute volumes)
```

when at least two prior bars and a positive median exist; otherwise `None`.

- [ ] **Step 6: Run targeted + existing feature tests**

```bash
PYTHONPATH=. pytest -q tests/live/test_symbol_state_features.py tests/test_core_features.py tests/test_features.py
```

- [ ] **Step 7: Commit**

```bash
git add scanner/live/symbol_state.py scanner/live/feature_engine.py tests/live/test_symbol_state_features.py
git commit -m "feat: add shared live symbol state and features"
```

---

### Task 4: Strategy adapter protocol, registry, and authoritative evidence gating

**Files:**
- Create: `scanner/live/strategy_registry.py`
- Test: `tests/live/test_strategy_registry.py`

**Interfaces:**
- Consumes: `StrategyDescriptor`, `StrategyIntent`, `FeatureSnapshot`, `SymbolState`.
- Produces protocol: `LiveStrategyAdapter.descriptor`, `evaluate(state, features, prior_event) -> StrategyIntent | None`.
- Produces: `StrategyRegistry.register(adapter)`, `enabled()`, `descriptor(strategy_id, variant_id)`, `from_leaderboard(adapters, leaderboard)`.

- [ ] **Step 1: Write failing registry test proving research cannot self-promote**

```python
import pandas as pd

from scanner.live.models import ProductionStatus
from scanner.live.strategy_registry import StrategyRegistry


def test_registry_takes_production_eligibility_from_authoritative_leaderboard():
    adapter = FakeAdapter(strategy_id="ORB", variant_id="ORB_LONG_BREAK", evidence_score=99.0)
    leaderboard = pd.DataFrame([{
        "strategy_id": "ORB",
        "variant_id": "ORB_LONG_BREAK",
        "direction": "LONG",
        "production_eligible": False,
        "robustness_score": 0.91,
    }])
    registry = StrategyRegistry.from_leaderboard([adapter], leaderboard)
    descriptor = registry.descriptor("ORB", "ORB_LONG_BREAK")
    assert descriptor.production_eligible is False
    assert descriptor.production_status is ProductionStatus.RESEARCH
    assert descriptor.evidence_score == 91.0
```

- [ ] **Step 2: Add test for eligible row**

When the exact strategy/variant/direction row has `production_eligible=True`, status becomes `PRODUCTION_ELIGIBLE`. Missing leaderboard rows remain `RESEARCH`, never eligible by default.

- [ ] **Step 3: Run RED**

```bash
PYTHONPATH=. pytest -q tests/live/test_strategy_registry.py
```

- [ ] **Step 4: Implement protocol and exact leaderboard mapping**

Use `typing.Protocol` with runtime-checkable shape:

```python
class LiveStrategyAdapter(Protocol):
    @property
    def descriptor(self) -> StrategyDescriptor: ...
    def evaluate(
        self,
        state: SymbolState,
        features: FeatureSnapshot,
        prior_event: LiveSignalEvent | None,
    ) -> StrategyIntent | None: ...
```

`from_leaderboard` must match on `strategy_id`, `variant_id`, and `direction`. Convert `robustness_score` from 0-1 to 0-100. Never inspect test/forward performance to change eligibility.

- [ ] **Step 5: Run tests plus production-hurdle regression**

```bash
PYTHONPATH=. pytest -q tests/live/test_strategy_registry.py tests/test_strategy_ranker.py
```

- [ ] **Step 6: Commit**

```bash
git add scanner/live/strategy_registry.py tests/live/test_strategy_registry.py
git commit -m "feat: add authoritative live strategy registry"
```

---

### Task 5: Lifecycle engine, production gating, and transition de-duplication

**Files:**
- Create: `scanner/live/lifecycle.py`
- Create: `scanner/live/signal_bus.py`
- Test: `tests/live/test_lifecycle.py`

**Interfaces:**
- Consumes: `StrategyIntent`, `FeedHealth`, prior `LiveSignalEvent`.
- Produces: `LifecycleEngine.apply(intent, feed_health) -> LiveSignalEvent | None`.
- Produces: `SignalBus.publish(event)`, `SignalBus.subscribe(callback)`.

- [ ] **Step 1: Write failing monotonic-transition test**

```python
from scanner.live.lifecycle import LifecycleEngine
from scanner.live.models import FeedHealth, LifecycleState


def test_lifecycle_is_monotonic_and_duplicate_transition_is_suppressed():
    engine = LifecycleEngine()
    watch = make_intent(LifecycleState.WATCH, production=True)
    armed = make_intent(LifecycleState.ARMED, production=True, setup_anchor=watch.setup_anchor)

    first = engine.apply(watch, FeedHealth.LIVE)
    assert first.effective_state is LifecycleState.WATCH
    assert engine.apply(watch, FeedHealth.LIVE) is None
    second = engine.apply(armed, FeedHealth.LIVE)
    assert second.effective_state is LifecycleState.ARMED

    with pytest.raises(ValueError):
        engine.apply(make_intent(LifecycleState.DISCOVER, production=True, setup_anchor=watch.setup_anchor), FeedHealth.LIVE)
```

- [ ] **Step 2: Write failing research-FIRE and stale-feed tests**

```python
def test_research_fire_is_labeled_but_never_production_fire():
    event = LifecycleEngine().apply(make_intent(LifecycleState.FIRE, production=False), FeedHealth.LIVE)
    assert event.effective_state is LifecycleState.FIRE
    assert event.action_label == "RESEARCH FIRE"


def test_stale_feed_blocks_new_production_fire():
    event = LifecycleEngine().apply(make_intent(LifecycleState.FIRE, production=True), FeedHealth.STALE)
    assert event.effective_state is LifecycleState.DATA_DEGRADED
    assert event.action_label == "DATA DEGRADED"
```

- [ ] **Step 3: Run RED**

```bash
PYTHONPATH=. pytest -q tests/live/test_lifecycle.py
```

- [ ] **Step 4: Implement allowed transition table**

Allowed normal progression:

```text
DISCOVER -> WATCH | ARMED | INVALIDATED | EXPIRED
WATCH -> ARMED | INVALIDATED | EXPIRED | DATA_DEGRADED | HALTED
ARMED -> FIRE | INVALIDATED | EXPIRED | DATA_DEGRADED | HALTED
FIRE -> MANAGE | EXIT | INVALIDATED | DATA_DEGRADED | HALTED
MANAGE -> EXIT | INVALIDATED | DATA_DEGRADED | HALTED
DATA_DEGRADED -> WATCH | ARMED | INVALIDATED | EXPIRED
HALTED -> WATCH | ARMED | INVALIDATED | EXPIRED
```

A fresh logical setup has a new stable `signal_id`; therefore backward transitions on the same ID are errors, not resets.

- [ ] **Step 5: Implement action-label mapping**

Production eligible:
- `FIRE + LONG` -> `FIRE LONG`
- `FIRE + SHORT` -> `FIRE SHORT`
- `ARMED + LONG` -> `ARMED LONG`
- `ARMED + SHORT` -> `ARMED SHORT`

Non-production FIRE -> `RESEARCH FIRE`.

`STALE`, `DISCONNECTED`, `RECOVERING` must not yield a new production FIRE; convert the attempted transition to `DATA_DEGRADED` and preserve the original attempted state in event metadata.

- [ ] **Step 6: Implement `SignalBus` as a synchronous append-only fan-out**

No threading in Phase 1. Subscribers receive each emitted event once. Subscriber exceptions are collected and re-raised as `SignalDispatchError` after every subscriber has been attempted, so one sink cannot prevent the ledger sink from seeing an event.

- [ ] **Step 7: Run tests**

```bash
PYTHONPATH=. pytest -q tests/live/test_lifecycle.py
```

- [ ] **Step 8: Commit**

```bash
git add scanner/live/lifecycle.py scanner/live/signal_bus.py tests/live/test_lifecycle.py
git commit -m "feat: add gated live signal lifecycle"
```

---

### Task 6: Correlation-aware consensus and normalized 0-100 live ranker

**Files:**
- Create: `scanner/live/consensus.py`
- Create: `scanner/live/ranker.py`
- Test: `tests/live/test_consensus_ranker.py`

**Interfaces:**
- Produces: `ConsensusSnapshot` dataclass in `scanner/live/models.py`.
- Produces: `build_consensus(events: list[LiveSignalEvent]) -> dict[tuple[str, Direction], ConsensusSnapshot]`.
- Produces: `rank_event(event, features, consensus) -> float` and `rank_active(events, features_by_symbol) -> list[RankedOpportunity]`.

- [ ] **Step 1: Write failing diminishing-correlation test**

```python
def test_two_variants_in_same_family_do_not_count_as_two_independent_edges():
    one = event(strategy="ORB", variant="ORB_LONG_BREAK", correlation="ORB", setup_score=80)
    two = event(strategy="ORB", variant="ORB_LONG_PULLBACK", correlation="ORB", setup_score=80)
    three = event(strategy="VWAP", variant="VWAP_LONG_RECLAIM", correlation="VWAP", setup_score=80)

    same_family = build_consensus([one, two])[("ABC", Direction.LONG)]
    independent = build_consensus([one, three])[("ABC", Direction.LONG)]
    assert independent.weighted_family_score > same_family.weighted_family_score
```

- [ ] **Step 2: Write failing conflict test**

A symbol with active LONG and SHORT ARMED/FIRE family evidence must mark both direction snapshots `conflict=True` and `confidence_label="CONFLICT"`.

- [ ] **Step 3: Write failing score-composition test**

Use exact weights from the spec:

```python
score = (
    0.35 * evidence
    + 0.20 * setup
    + 0.15 * participation
    + 0.10 * catalyst
    + 0.10 * consensus
    + 0.05 * execution
    + 0.05 * regime
)
```

Clamp each component and final score to `0..100`. `UNKNOWN` catalyst is neutral `50.0`, not falsely positive. Conflict applies a 20-point penalty after weighted composition. Feed health other than `LIVE`/`DELAYED` caps score at 49 and cannot change lifecycle gating.

- [ ] **Step 4: Run RED**

```bash
PYTHONPATH=. pytest -q tests/live/test_consensus_ranker.py
```

- [ ] **Step 5: Implement diminishing family contribution**

For signals in one correlation group, sorted strongest first, use multipliers `1.00`, `0.35`, then `0.15` for each additional variant. Normalize the resulting independent-family evidence to 0-100 using the sum of the strongest possible contributions for the observed number of groups; never let more parameter variants inflate the value above an additional independent family.

- [ ] **Step 6: Implement participation/regime inputs explicitly**

`participation_score(features)`:
- use `rvol` and `volume_acceleration` only when known;
- score each known input to 0-100 via bounded monotonic helpers;
- if neither is known return 50.

`regime_score` is supplied by adapter metadata when validated, otherwise neutral 50. Do not infer time-of-day edge from clock time alone.

- [ ] **Step 7: Run tests**

```bash
PYTHONPATH=. pytest -q tests/live/test_consensus_ranker.py
```

- [ ] **Step 8: Commit**

```bash
git add scanner/live/models.py scanner/live/consensus.py scanner/live/ranker.py tests/live/test_consensus_ranker.py
git commit -m "feat: add consensus-aware live ranking"
```

---

### Task 7: Idempotent SQLite forward ledger and restart state

**Files:**
- Create: `scanner/live/forward_ledger.py`
- Test: `tests/live/test_forward_ledger.py`
- Modify: `.gitignore` only if `data/live/*.db` is not already excluded.

**Interfaces:**
- Produces: `ForwardLedger(path)`.
- Methods: `append_event(event, features) -> bool`, `append_health(timestamp, state, details) -> bool`, `latest_events(session_date) -> list[LiveSignalEvent]`, `event_count() -> int`, `close()`.

- [ ] **Step 1: Write failing idempotency test**

```python
def test_forward_ledger_is_idempotent_by_event_id(tmp_path):
    ledger = ForwardLedger(tmp_path / "live.db")
    e = event(strategy="ORB", variant="ORB_LONG_BREAK", state=LifecycleState.FIRE)
    assert ledger.append_event(e, feature_snapshot()) is True
    assert ledger.append_event(e, feature_snapshot()) is False
    assert ledger.event_count() == 1
```

- [ ] **Step 2: Write failing restart-read test**

Open a second `ForwardLedger` instance on the same file and require `latest_events(date)` to reconstruct the latest event for each signal ID without changing IDs or action labels.

- [ ] **Step 3: Run RED**

```bash
PYTHONPATH=. pytest -q tests/live/test_forward_ledger.py
```

- [ ] **Step 4: Implement schema**

Create tables exactly once:

```sql
CREATE TABLE IF NOT EXISTS signal_events (
    event_id TEXT PRIMARY KEY,
    signal_id TEXT NOT NULL,
    strategy_id TEXT NOT NULL,
    variant_id TEXT NOT NULL,
    strategy_version TEXT NOT NULL,
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL,
    event_timestamp TEXT NOT NULL,
    setup_anchor TEXT NOT NULL,
    effective_state TEXT NOT NULL,
    action_label TEXT NOT NULL,
    production_status TEXT NOT NULL,
    production_eligible INTEGER NOT NULL,
    reference_price REAL NOT NULL,
    entry_trigger REAL,
    stop_reference REAL,
    target_1 REAL,
    target_2 REAL,
    setup_score REAL NOT NULL,
    evidence_score REAL NOT NULL,
    execution_score REAL NOT NULL,
    feed_health TEXT NOT NULL,
    feature_json TEXT NOT NULL,
    reason_codes_json TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    inserted_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_signal_events_session
ON signal_events(symbol, event_timestamp);

CREATE TABLE IF NOT EXISTS scanner_health (
    health_id TEXT PRIMARY KEY,
    event_timestamp TEXT NOT NULL,
    state TEXT NOT NULL,
    details_json TEXT NOT NULL
);
```

Use `INSERT OR IGNORE` keyed by `event_id`; return whether a row was inserted.

- [ ] **Step 5: Implement serialization with enum/string stability**

Use explicit `json.dumps(..., sort_keys=True, default=str)`. Do not pickle Python objects into SQLite.

- [ ] **Step 6: Run tests**

```bash
PYTHONPATH=. pytest -q tests/live/test_forward_ledger.py
```

- [ ] **Step 7: Commit**

```bash
git add scanner/live/forward_ledger.py tests/live/test_forward_ledger.py .gitignore
git commit -m "feat: add idempotent live forward ledger"
```

---

### Task 8: Refactor ORB and VWAP into reusable no-lookahead trigger decisions, then add live parity adapters

**Files:**
- Modify: `scanner/core/models.py`
- Modify: `scanner/strategies/orb_stocks_in_play/strategy.py`
- Modify: `scanner/strategies/vwap_momentum/strategy.py`
- Create: `scanner/live/adapters/__init__.py`
- Create: `scanner/live/adapters/orb.py`
- Create: `scanner/live/adapters/vwap.py`
- Test: `tests/live/test_orb_live_parity.py`
- Test: `tests/live/test_vwap_live_parity.py`
- Regression: `tests/test_orb_strategy.py`, existing VWAP strategy tests/end-to-end tests.

**Interfaces:**
- Add frozen `TriggerDecision` to `scanner/core/models.py` with fields: `variant_id`, `direction`, `signal_timestamp`, `reference_price`, `stop_reference`, `setup_metadata`.
- Add `detect_orb_triggers(bars, context, cfg=None) -> list[TriggerDecision]`.
- Add `detect_vwap_triggers(bars, context, cfg=None) -> list[TriggerDecision]`.
- Existing `generate_orb_signals(...)` and `generate_vwap_signals(...)` retain their public signatures and output schema.
- Produce adapters `ORBLiveAdapter` and `VWAPLiveAdapter` implementing `LiveStrategyAdapter`.

- [ ] **Step 1: Freeze existing batch behavior before refactor**

Extend existing strategy tests with exact expected variant, signal timestamp, direction, stop reference, and next-bar entry for representative long and short fixtures. Run them before changing code:

```bash
PYTHONPATH=. pytest -q tests/test_orb_strategy.py tests/test_no_cost_vwap_end_to_end.py
```

Expected: PASS before refactor.

- [ ] **Step 2: Write failing ORB prefix-parity test**

The test must:
1. build an existing synthetic ORB day fixture;
2. call `generate_orb_signals(full_bars, context)` for the batch truth;
3. feed bars one at a time into `SymbolState`;
4. call `ORBLiveAdapter.evaluate(...)` after each completed bar;
5. assert the first live FIRE's `event_timestamp` equals the batch `signal_timestamp`, `variant_id` matches, direction matches, and stop reference matches;
6. assert no FIRE was emitted before the batch signal timestamp.

- [ ] **Step 3: Write failing VWAP prefix-parity test**

Use the same shape for `VWAP_LONG_RECLAIM` and `VWAP_SHORT_REJECTION`.

- [ ] **Step 4: Run RED parity tests**

```bash
PYTHONPATH=. pytest -q tests/live/test_orb_live_parity.py tests/live/test_vwap_live_parity.py
```

- [ ] **Step 5: Extract pure decision detection from ORB without changing batch output**

Move only the trigger-identification logic into `detect_orb_triggers`. It may inspect only the supplied bar prefix. It must never require a future/next bar. `generate_orb_signals` then:

```python
for decision in detect_orb_triggers(bars, context, cfg):
    signal_idx = index_for_timestamp(decision.signal_timestamp)
    next_idx = signal_idx + 1
    if next_idx is not executable in the same session:
        continue
    rows.append(_base_signal_from_decision(decision, next_bar, context, cfg))
```

The resulting DataFrame must remain byte-for-byte equivalent in the fields covered by existing tests.

- [ ] **Step 6: Extract pure decision detection from VWAP using the same pattern**

No new strategy thresholds. The extraction must preserve the exact existing conditions from `generate_vwap_signals`.

- [ ] **Step 7: Implement adapters as thin wrappers**

Each adapter:
- calls the corresponding `detect_*_triggers(state.bars_frame(), features.context)`;
- selects only a decision whose `signal_timestamp == state.latest.timestamp` and has not already been represented by `prior_event`;
- returns `StrategyIntent(state=FIRE, ...)` for a newly completed trigger;
- may return `WATCH`/`ARMED` later in Phase 1 only where a deterministic pre-trigger state can be derived without changing the locked rule; FIRE parity takes precedence;
- uses `features.last_price` as current reference price and the decision's structural stop;
- sets setup score from deterministic setup metadata, clamped 0-100; no historical evidence is embedded in the adapter.

- [ ] **Step 8: Run parity and all existing ORB/VWAP regressions**

```bash
PYTHONPATH=. pytest -q \
  tests/live/test_orb_live_parity.py \
  tests/live/test_vwap_live_parity.py \
  tests/test_orb_strategy.py \
  tests/test_no_cost_vwap_end_to_end.py \
  tests/test_no_cost_end_to_end.py
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add scanner/core/models.py scanner/strategies/orb_stocks_in_play scanner/strategies/vwap_momentum scanner/live/adapters tests/live/test_orb_live_parity.py tests/live/test_vwap_live_parity.py
git commit -m "refactor: share ORB and VWAP decisions with live scanner"
```

---

### Task 9: Add SerClick/Leo prefix adapter and batch/live ignition parity

**Files:**
- Create: `scanner/live/adapters/serclick_leo.py`
- Modify: `scanner/strategies/serclick_leo/strategy.py` only if a pure row-to-intent helper is required.
- Test: `tests/live/test_serclick_live_parity.py`
- Regression: `tests/test_no_cost_serclick_end_to_end.py`, `tests/test_pipeline.py`, SerClick feature/study tests.

**Interfaces:**
- Reuse: `scanner.serclick.features.analyze_candidate_day(prefix_bars, qualification, cfg)`.
- Reuse: `scanner.strategies.serclick_leo.strategy.adapt_serclick_ignitions(...)` for normalized ignition fields.
- Produce: `SerClickLeoLiveAdapter` implementing `LiveStrategyAdapter`.

- [ ] **Step 1: Write failing ignition-prefix parity test**

Build the same deterministic candidate/qualification used in SerClick tests. Compute batch truth with `analyze_candidate_day(full_bars, qualification, cfg)` and take the first `event_type == "IGNITION"`. Then pass progressively larger prefixes to the live adapter and assert:
- no live FIRE before the ignition timestamp;
- first FIRE timestamp equals batch ignition timestamp;
- normalized variant from `_variant(population, ignition_window)` matches `adapt_serclick_ignitions`;
- morning observation variants remain research-gated unless registry evidence says otherwise.

- [ ] **Step 2: Run RED**

```bash
PYTHONPATH=. pytest -q tests/live/test_serclick_live_parity.py
```

- [ ] **Step 3: Implement prefix adapter without copying SerClick rules**

For each evaluation:
1. read `qualification` and `serclick_config` from `FeatureSnapshot.context`;
2. call `analyze_candidate_day` on `state.bars_frame()` only;
3. select transitions/events at the latest completed bar timestamp;
4. map `IGNITION` to FIRE; map known pre-ignition transition states to WATCH/ARMED only if their semantics are already explicit in source output;
5. normalize an ignition through `adapt_serclick_ignitions` so variant/time-window logic remains single-sourced;
6. never infer a SerClick event absent from `analyze_candidate_day`.

- [ ] **Step 4: Run SerClick regressions**

```bash
PYTHONPATH=. pytest -q \
  tests/live/test_serclick_live_parity.py \
  tests/test_no_cost_serclick_end_to_end.py \
  tests/test_pipeline.py \
  tests/test_features.py
```

- [ ] **Step 5: Commit**

```bash
git add scanner/live/adapters/serclick_leo.py scanner/strategies/serclick_leo/strategy.py tests/live/test_serclick_live_parity.py
git commit -m "feat: add SerClick Leo live parity adapter"
```

---

### Task 10: Deterministic fake stream and scanner orchestration service

**Files:**
- Create: `scanner/live/fake_stream.py`
- Create: `scanner/live/service.py`
- Test: `tests/live/test_live_service_end_to_end.py`

**Interfaces:**
- Produces: `FakeMarketStream(events)` iterable.
- Produces: `ScannerService(registry, ledger, feature_engine, lifecycle, feed_health)`.
- Methods: `process_bar(bar, context) -> list[LiveSignalEvent]`, `active_events()`, `ranked_snapshot()`.

- [ ] **Step 1: Write failing API-free long-FIRE end-to-end test**

Use a fake ORB day and a registry descriptor marked production eligible. Monkeypatch network access to raise if `requests` is called. Feed bars through `ScannerService.process_bar`. Assert:
- exactly one production `FIRE LONG` transition;
- it is persisted once;
- `ranked_snapshot()[0]` is that symbol;
- no duplicate FIRE after additional bars.

- [ ] **Step 2: Add research-only trigger scenario**

Same market data, descriptor not eligible. Assert action is exactly `RESEARCH FIRE`, persisted, and never appears as `FIRE LONG`.

- [ ] **Step 3: Add multi-edge consensus and conflict scenarios**

Use deterministic fake adapters in the test:
- ORB + VWAP same direction -> confidence at least `CONFIRMED` and score greater than either single-edge equivalent;
- long ORB + strong short fake adapter -> `CONFLICT` and penalty applied.

- [ ] **Step 4: Add stale-feed block and restart/no-duplicate scenario**

1. force health `STALE` before a would-be FIRE -> event becomes `DATA_DEGRADED`;
2. close service/ledger;
3. recreate service using the same database;
4. restore latest session events from ledger;
5. replay the last already-seen bar and assert no duplicate event row and no fabricated FIRE.

- [ ] **Step 5: Run RED**

```bash
PYTHONPATH=. pytest -q tests/live/test_live_service_end_to_end.py
```

- [ ] **Step 6: Implement orchestration only in `ScannerService`**

`process_bar` order is fixed:

```text
validate/append bar
-> update feed health from timestamp
-> build one FeatureSnapshot
-> evaluate each enabled adapter exactly once
-> lifecycle.apply each intent
-> persist emitted transition
-> publish emitted transition
-> rebuild consensus/ranking snapshot
```

`ScannerService` must not contain ORB/VWAP/SerClick thresholds.

- [ ] **Step 7: Implement restore behavior**

At construction, optionally pass `restore_session_date`. Load latest events from ledger into lifecycle's in-memory prior-state map. A repeated event derives the same stable event ID and is ignored by both lifecycle de-dup and SQLite primary key.

Do not implement real reconnect gap recovery yet; that belongs to Phase 2 with the real stream. Phase 1 proves restart idempotency only.

- [ ] **Step 8: Run complete Phase 1 test suite**

```bash
PYTHONPATH=. pytest -q tests/live tests/test_core_models.py tests/test_core_features.py tests/test_orb_strategy.py tests/test_no_cost_vwap_end_to_end.py tests/test_no_cost_serclick_end_to_end.py tests/test_no_cost_end_to_end.py tests/test_strategy_ranker.py
python -m compileall -q scanner
```

Expected: all PASS, compile success, no network access used by `tests/live`.

- [ ] **Step 9: Commit**

```bash
git add scanner/live/fake_stream.py scanner/live/service.py tests/live/test_live_service_end_to_end.py
git commit -m "feat: complete API-free unified scanner core"
```

---

### Task 11: Phase 1 acceptance verification and documentation handoff

**Files:**
- Modify: `README.md`
- Create: `docs/research/unified_live_scanner_phase1.md`
- Test: no new production code; run verification only.

**Interfaces:**
- Documents exact Phase 1 status and the execution boundary before Phase 2.

- [ ] **Step 1: Add concise README section**

Document:
- API-free live core exists;
- ORB/VWAP/SerClick parity tests;
- lifecycle labels;
- production/research gating;
- SQLite forward ledger;
- fake-stream command/test;
- explicit statement: no real SIP connection and no order routing yet.

- [ ] **Step 2: Create Phase 1 methodology note**

`docs/research/unified_live_scanner_phase1.md` must record:
- stable ID scheme;
- point-in-time feature rule;
- parity definition;
- correlation multipliers `1.00/0.35/0.15`;
- exact scoring weights;
- research-FIRE labeling rule;
- stale/recovery production block;
- SQLite tables;
- which acceptance criteria are deferred to Phase 2 (real SIP session, real reconnect gaps, action-board UI/console refresh).

- [ ] **Step 3: Run the complete existing repository suite**

```bash
PYTHONPATH=. pytest -q
python -m compileall -q scanner scripts
```

Expected: all repository tests pass; compile succeeds.

- [ ] **Step 4: Verify no credential/order-routing regression**

Run:

```bash
git grep -nE "APCA_API_SECRET_KEY|sk-[A-Za-z0-9]|submit_order|place_order|create_order" -- ':!docs/superpowers/*'
```

Expected: no newly introduced secret values and no Phase 1 broker-order implementation. Existing references to environment-variable names/documentation are acceptable; literal credentials are not.

- [ ] **Step 5: Review diff for strategy parity and scope**

```bash
git diff main...HEAD --stat
git diff main...HEAD -- scanner/strategies scanner/live tests/live
```

Confirm:
- ORB/VWAP batch public APIs retained;
- SerClick rules were not duplicated into the live package;
- no unrelated refactor;
- no real network stream introduced.

- [ ] **Step 6: Commit docs**

```bash
git add README.md docs/research/unified_live_scanner_phase1.md
git commit -m "docs: document unified scanner phase 1"
```

- [ ] **Step 7: Final verification evidence**

Record the exact final outputs of:

```bash
PYTHONPATH=. pytest -q
python -m compileall -q scanner scripts
git status --short
```

A clean status and green suite are required before calling Phase 1 complete.

---

## Phase 1 Definition of Done

Phase 1 is complete only when:

1. `tests/live` runs without network access.
2. ORB live FIRE decisions match batch ORB trigger timestamp/variant/direction/structural stop on locked synthetic fixtures.
3. VWAP live FIRE decisions match batch VWAP trigger timestamp/variant/direction/structural stop.
4. SerClick/Leo first live ignition matches batch prefix truth.
5. Research-only strategies cannot produce an unlabeled production FIRE.
6. `STALE`, `DISCONNECTED`, and `RECOVERING` block new production FIRE.
7. Duplicate lifecycle transitions do not alert/persist twice.
8. Consensus controls correlated variants and surfaces opposite-direction conflict.
9. Unified ranking uses the spec's exact 35/20/15/10/10/5/5 weighting and is explicitly not a probability of profit.
10. SQLite restart state reproduces stable signal/event identity and does not duplicate events.
11. Existing research and full repository tests remain green.
12. No real market-data network stream or broker order-routing code exists yet.

## Next Plan Boundary

After Phase 1 is green, write a separate Phase 2 implementation plan for:

- Alpaca SIP WebSocket/streaming transport;
- asset/candidate subscription staging;
- real feed-health lag and reconnect-gap reconciliation;
- missed-during-gap diagnostics;
- console/action-board presentation and refresh;
- prospective forward-ledger paper soak across premarket, regular session and after-hours;
- observability counters/latency;
- no broker routing.
