from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from scanner.live.consensus import build_consensus
from scanner.live.models import (
    Direction,
    FeedHealth,
    FeatureSnapshot,
    LifecycleState,
    LiveSignalEvent,
    MarketSession,
    ProductionStatus,
    StrategyDescriptor,
    StrategyIntent,
    stable_event_id,
    stable_signal_id,
)
from scanner.live.ranker import rank_event

ET = ZoneInfo("America/New_York")
BASE = datetime(2026, 9, 2, 10, 0, tzinfo=ET)


def _event(variant, group, direction=Direction.LONG, setup=80.0, evidence=80.0, health=FeedHealth.LIVE, minute=0, state=LifecycleState.ARMED, production=True, metadata=None):
    ts = BASE + timedelta(minutes=minute)
    descriptor = StrategyDescriptor(
        strategy_id=group,
        strategy_family=group,
        variant_id=variant,
        direction=direction,
        strategy_version=f"{group.lower()}-v1",
        production_status=(ProductionStatus.PRODUCTION_ELIGIBLE if production else ProductionStatus.RESEARCH),
        production_eligible=production,
        correlation_group=group,
        evidence_score=evidence,
    )
    intent = StrategyIntent(
        descriptor=descriptor,
        symbol="ABC",
        state=state,
        event_timestamp=ts,
        setup_anchor=BASE,
        reference_price=4.2,
        setup_score=setup,
        execution_score=90.0,
        reason_codes=("TEST",),
        explanation="test",
        metadata=metadata or {},
    )
    signal_id = stable_signal_id(descriptor.strategy_id, variant, "ABC", direction, BASE, descriptor.strategy_version)
    return LiveSignalEvent(
        event_id=stable_event_id(signal_id, state, ts),
        signal_id=signal_id,
        intent=intent,
        effective_state=state,
        action_label=("ARMED LONG" if direction is Direction.LONG else "ARMED SHORT"),
        feed_health=health,
        source_timestamp=ts,
    )


def _features(**overrides):
    values = dict(
        symbol="ABC",
        timestamp=BASE,
        session=MarketSession.REGULAR,
        last_price=4.2,
        rvol=5.0,
        volume_acceleration=1.5,
        catalyst_class="UNKNOWN",
        context={},
    )
    values.update(overrides)
    return FeatureSnapshot(**values)


def test_independent_strategy_families_beat_correlated_variants():
    orb_break = _event("ORB_LONG_BREAK", "ORB")
    orb_pullback = _event("ORB_LONG_PULLBACK", "ORB", minute=1)
    vwap = _event("VWAP_LONG_RECLAIM", "VWAP", minute=1)

    correlated = build_consensus([orb_break, orb_pullback])[("ABC", Direction.LONG)]
    independent = build_consensus([orb_break, vwap])[("ABC", Direction.LONG)]

    assert independent.weighted_score > correlated.weighted_score
    assert correlated.active_families == 1
    assert correlated.confidence_label == "SINGLE_EDGE"
    assert independent.active_families == 2
    assert independent.confidence_label == "CONFIRMED"


def test_opposite_active_directions_surface_conflict_on_both_sides():
    long_event = _event("ORB_LONG_BREAK", "ORB", Direction.LONG)
    short_event = _event("BFR_SHORT", "BFR", Direction.SHORT)

    consensus = build_consensus([long_event, short_event])
    long_side = consensus[("ABC", Direction.LONG)]
    short_side = consensus[("ABC", Direction.SHORT)]

    assert long_side.conflict is True
    assert short_side.conflict is True
    assert long_side.confidence_label == "CONFLICT"
    assert short_side.confidence_label == "CONFLICT"


def test_rank_event_uses_locked_weight_formula_and_neutral_unknowns():
    event = _event(
        "ORB_LONG_BREAK",
        "ORB",
        setup=70.0,
        evidence=80.0,
        metadata={"regime_validated": True, "regime_score": 60.0},
    )
    features = _features(
        rvol=5.0,
        volume_acceleration=1.5,
        catalyst_class="NEWS",
        context={"catalyst_score": 90.0},
    )
    consensus = build_consensus([event])[("ABC", Direction.LONG)]

    # participation: rvol 5x -> 50, acceleration 1.5x -> 50; average 50.
    expected = (
        0.35 * 80.0
        + 0.20 * 70.0
        + 0.15 * 50.0
        + 0.10 * 90.0
        + 0.10 * consensus.weighted_score
        + 0.05 * 90.0
        + 0.05 * 60.0
    )
    assert rank_event(event, features, consensus) == pytest.approx(expected)

    unknowns = _features(rvol=None, volume_acceleration=None, catalyst_class="UNKNOWN", context={})
    neutral_event = _event("ORB_LONG_BREAK", "ORB", metadata={})
    neutral_consensus = build_consensus([neutral_event])[("ABC", Direction.LONG)]
    neutral_score = rank_event(neutral_event, unknowns, neutral_consensus)
    assert 0.0 <= neutral_score <= 100.0


def test_conflict_penalty_and_stale_cap_are_applied_after_composition():
    long_event = _event("ORB_LONG_BREAK", "ORB", setup=100, evidence=100, health=FeedHealth.STALE, metadata={"regime_validated": True, "regime_score": 100.0})
    short_event = _event("BFR_SHORT", "BFR", Direction.SHORT, setup=100, evidence=100)
    features = _features(rvol=10.0, volume_acceleration=3.0, catalyst_class="NEWS", context={"catalyst_score": 100.0})
    consensus = build_consensus([long_event, short_event])[("ABC", Direction.LONG)]

    score = rank_event(long_event, features, consensus)
    assert consensus.conflict is True
    assert score <= 49.0
