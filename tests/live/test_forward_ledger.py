from datetime import date, datetime
from zoneinfo import ZoneInfo

from scanner.live.forward_ledger import ForwardLedger
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

ET = ZoneInfo("America/New_York")
TS = datetime(2026, 9, 2, 10, 15, tzinfo=ET)


def _event():
    descriptor = StrategyDescriptor(
        strategy_id="ORB",
        strategy_family="ORB",
        variant_id="ORB_LONG_BREAK",
        direction=Direction.LONG,
        strategy_version="orb-v1",
        production_status=ProductionStatus.PRODUCTION_ELIGIBLE,
        production_eligible=True,
        correlation_group="ORB",
        evidence_score=82.0,
        required_features=("session_vwap",),
    )
    intent = StrategyIntent(
        descriptor=descriptor,
        symbol="ABC",
        state=LifecycleState.FIRE,
        event_timestamp=TS,
        setup_anchor=datetime(2026, 9, 2, 10, 10, tzinfo=ET),
        reference_price=4.25,
        setup_score=88.0,
        execution_score=91.0,
        reason_codes=("ORB_BREAK", "RVOL_OK"),
        explanation="locked opening range broke on completed bar",
        entry_trigger=4.26,
        stop_reference=4.05,
        target_1=4.47,
        target_2=4.68,
        management_policy="R_MULTIPLE",
        metadata={"regime_validated": True, "regime_score": 70.0},
    )
    signal_id = stable_signal_id(
        descriptor.strategy_id,
        descriptor.variant_id,
        intent.symbol,
        descriptor.direction,
        intent.setup_anchor,
        descriptor.strategy_version,
    )
    return LiveSignalEvent(
        event_id=stable_event_id(signal_id, LifecycleState.FIRE, TS),
        signal_id=signal_id,
        intent=intent,
        effective_state=LifecycleState.FIRE,
        action_label="FIRE LONG",
        feed_health=FeedHealth.LIVE,
        source_timestamp=TS,
    )


def _features():
    return FeatureSnapshot(
        symbol="ABC",
        timestamp=TS,
        session=MarketSession.REGULAR,
        last_price=4.25,
        session_vwap=4.10,
        hod=4.30,
        lod=3.95,
        gap_pct=0.25,
        rvol=6.0,
        volume_acceleration=2.0,
        spread_pct=0.004,
        catalyst_class="NEWS",
        market_cap_bucket="<300M",
        float_bucket="5-10M",
        time_of_day_bucket="09:30-10:30",
        context={"catalyst_score": 80.0},
    )


def test_append_event_is_idempotent(tmp_path):
    ledger = ForwardLedger(tmp_path / "live.db")
    event = _event()

    assert ledger.append_event(event, _features()) is True
    assert ledger.append_event(event, _features()) is False
    assert ledger.event_count() == 1
    ledger.close()


def test_restart_reconstructs_stable_event_identity(tmp_path):
    path = tmp_path / "live.db"
    event = _event()
    first = ForwardLedger(path)
    assert first.append_event(event, _features()) is True
    first.close()

    reopened = ForwardLedger(path)
    restored = reopened.latest_events(date(2026, 9, 2))
    assert len(restored) == 1
    actual = restored[0]
    assert actual.event_id == event.event_id
    assert actual.signal_id == event.signal_id
    assert actual.intent.descriptor.strategy_id == "ORB"
    assert actual.intent.descriptor.variant_id == "ORB_LONG_BREAK"
    assert actual.intent.descriptor.direction is Direction.LONG
    assert actual.effective_state is LifecycleState.FIRE
    assert actual.action_label == "FIRE LONG"
    assert actual.intent.entry_trigger == 4.26
    assert actual.intent.stop_reference == 4.05
    assert actual.intent.target_1 == 4.47
    assert actual.intent.reason_codes == ("ORB_BREAK", "RVOL_OK")
    reopened.close()


def test_health_writes_are_idempotent(tmp_path):
    ledger = ForwardLedger(tmp_path / "live.db")
    assert ledger.append_health(TS, FeedHealth.STALE, {"lag_seconds": 95.0}) is True
    assert ledger.append_health(TS, FeedHealth.STALE, {"lag_seconds": 95.0}) is False
    ledger.close()
