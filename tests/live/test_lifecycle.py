from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from scanner.live.lifecycle import LifecycleEngine
from scanner.live.models import (
    Direction,
    FeedHealth,
    LifecycleState,
    ProductionStatus,
    StrategyDescriptor,
    StrategyIntent,
)
from scanner.live.signal_bus import SignalBus, SignalDispatchError

ET = ZoneInfo("America/New_York")


def _descriptor(production=True):
    return StrategyDescriptor(
        strategy_id="ORB",
        strategy_family="ORB",
        variant_id="ORB_LONG_BREAK",
        direction=Direction.LONG,
        strategy_version="orb-v1",
        production_status=(ProductionStatus.PRODUCTION_ELIGIBLE if production else ProductionStatus.RESEARCH),
        production_eligible=production,
        correlation_group="ORB",
        evidence_score=80.0 if production else 30.0,
    )


def _intent(state, minute, production=True):
    anchor = datetime(2026, 9, 2, 9, 35, tzinfo=ET)
    return StrategyIntent(
        descriptor=_descriptor(production),
        symbol="ABC",
        state=state,
        event_timestamp=datetime(2026, 9, 2, 9, minute, tzinfo=ET),
        setup_anchor=anchor,
        reference_price=4.2,
        setup_score=80.0,
        execution_score=90.0,
        reason_codes=("TEST",),
        explanation="test intent",
        entry_trigger=4.2,
        stop_reference=4.0,
    )


def test_lifecycle_dedupes_and_rejects_backwards_transition():
    engine = LifecycleEngine()
    watch = _intent(LifecycleState.WATCH, 35)
    first = engine.apply(watch, FeedHealth.LIVE)
    assert first is not None and first.effective_state is LifecycleState.WATCH
    assert engine.apply(watch, FeedHealth.LIVE) is None

    armed = engine.apply(_intent(LifecycleState.ARMED, 36), FeedHealth.LIVE)
    assert armed is not None and armed.effective_state is LifecycleState.ARMED

    with pytest.raises(ValueError):
        engine.apply(_intent(LifecycleState.WATCH, 37), FeedHealth.LIVE)


def test_production_and_research_fire_labels_are_unambiguous():
    production = LifecycleEngine()
    production.apply(_intent(LifecycleState.ARMED, 36, production=True), FeedHealth.LIVE)
    fire = production.apply(_intent(LifecycleState.FIRE, 37, production=True), FeedHealth.LIVE)
    assert fire.effective_state is LifecycleState.FIRE
    assert fire.action_label == "FIRE LONG"

    research = LifecycleEngine()
    research.apply(_intent(LifecycleState.ARMED, 36, production=False), FeedHealth.LIVE)
    research_fire = research.apply(_intent(LifecycleState.FIRE, 37, production=False), FeedHealth.LIVE)
    assert research_fire.effective_state is LifecycleState.FIRE
    assert research_fire.action_label == "RESEARCH FIRE"


def test_stale_feed_converts_production_fire_to_data_degraded():
    engine = LifecycleEngine()
    engine.apply(_intent(LifecycleState.ARMED, 36, production=True), FeedHealth.LIVE)
    blocked = engine.apply(_intent(LifecycleState.FIRE, 37, production=True), FeedHealth.STALE)
    assert blocked.effective_state is LifecycleState.DATA_DEGRADED
    assert blocked.action_label == "DATA DEGRADED"


def test_signal_bus_calls_all_subscribers_then_reports_errors():
    engine = LifecycleEngine()
    event = engine.apply(_intent(LifecycleState.WATCH, 35), FeedHealth.LIVE)
    calls = []
    bus = SignalBus()

    def bad(item):
        calls.append(("bad", item.event_id))
        raise RuntimeError("boom")

    def good(item):
        calls.append(("good", item.event_id))

    bus.subscribe(bad)
    bus.subscribe(good)

    with pytest.raises(SignalDispatchError) as exc:
        bus.publish(event)

    assert [name for name, _ in calls] == ["bad", "good"]
    assert len(exc.value.errors) == 1
