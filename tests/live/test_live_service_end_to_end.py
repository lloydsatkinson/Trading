from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from scanner.live.adapters.orb import ORBLiveAdapter
from scanner.live.fake_stream import FakeMarketStream
from scanner.live.feed_health import FeedHealthMonitor
from scanner.live.forward_ledger import ForwardLedger
from scanner.live.models import (
    Direction,
    LifecycleState,
    MarketBar,
    ProductionStatus,
    StrategyDescriptor,
    StrategyIntent,
)
from scanner.live.service import ScannerService
from scanner.live.strategy_registry import StrategyRegistry
from scanner.strategies.orb_stocks_in_play.config import ORBConfig

ET = ZoneInfo("America/New_York")


def _orb_rows():
    return [
        ("2026-08-28 09:30", 5.00, 5.20, 4.95, 5.10, 100),
        ("2026-08-28 09:31", 5.10, 5.30, 5.05, 5.20, 100),
        ("2026-08-28 09:32", 5.20, 5.40, 5.15, 5.35, 100),
        ("2026-08-28 09:33", 5.34, 5.38, 5.20, 5.25, 100),
        ("2026-08-28 09:34", 5.25, 5.35, 5.15, 5.20, 100),
        ("2026-08-28 09:35", 5.20, 5.36, 5.18, 5.30, 100),
        ("2026-08-28 09:36", 5.31, 5.65, 5.30, 5.60, 300),
        ("2026-08-28 09:37", 5.62, 5.80, 5.55, 5.75, 220),
    ]


def _orb_stream():
    return FakeMarketStream([
        MarketBar(
            "AAA",
            pd.Timestamp(ts, tz="America/New_York").to_pydatetime(),
            open_, high, low, close, volume,
        )
        for ts, open_, high, low, close, volume in _orb_rows()
    ])


def _orb_context():
    return {
        "symbol": "AAA",
        "date": "2026-08-28",
        "prior_close": 4.0,
        "market_cap": 150_000_000,
        "pm_gap_pct": 0.25,
        "pm_dollar_turnover": 5_000_000,
        "opening_rvol": 6.0,
        "float_shares": 8_000_000,
        "catalyst_class": "NEWS",
        "catalyst_score": 80.0,
        "split": "forward",
    }


def _orb_descriptor():
    return StrategyDescriptor(
        strategy_id="ORB",
        strategy_family="ORB",
        variant_id="ORB_LONG_BREAK",
        direction=Direction.LONG,
        strategy_version="orb-v1",
        production_status=ProductionStatus.RESEARCH,
        production_eligible=False,
        correlation_group="ORB",
        evidence_score=0.0,
    )


def _orb_registry(production_eligible: bool):
    cfg = ORBConfig(
        min_gap_pct=0.10,
        min_pm_dollar_turnover=2_000_000,
        min_opening_rvol=3.0,
        min_breakout_volume_ratio=1.5,
        min_clv=0.60,
    )
    adapter = ORBLiveAdapter(_orb_descriptor(), cfg)
    leaderboard = pd.DataFrame([{
        "strategy_id": "ORB",
        "variant_id": "ORB_LONG_BREAK",
        "direction": "LONG",
        "production_eligible": production_eligible,
        "robustness_score": 0.82,
    }])
    return StrategyRegistry.from_leaderboard([adapter], leaderboard)


def _block_http(*args, **kwargs):
    raise AssertionError("API-free live scanner attempted an HTTP request")


def test_production_orb_fire_is_api_free_persisted_once_and_ranked(tmp_path, monkeypatch):
    monkeypatch.setattr("requests.sessions.Session.request", _block_http)
    ledger = ForwardLedger(tmp_path / "live.db")
    service = ScannerService(_orb_registry(True), ledger)

    emitted = []
    for bar in _orb_stream():
        emitted.extend(service.process_bar(bar, _orb_context()))

    fires = [event for event in emitted if event.action_label == "FIRE LONG"]
    assert len(fires) == 1
    assert fires[0].intent.symbol == "AAA"
    assert ledger.event_count() == 1
    assert service.ranked_snapshot()[0].event.intent.symbol == "AAA"
    ledger.close()


def test_research_orb_never_masquerades_as_production_fire(tmp_path):
    ledger = ForwardLedger(tmp_path / "research.db")
    service = ScannerService(_orb_registry(False), ledger)
    emitted = []
    for bar in _orb_stream():
        emitted.extend(service.process_bar(bar, _orb_context()))

    assert [event.action_label for event in emitted] == ["RESEARCH FIRE"]
    assert ledger.event_count() == 1
    ledger.close()


class FixedFireAdapter:
    def __init__(self, descriptor: StrategyDescriptor, trigger_ts: datetime, setup_score: float = 80.0):
        self.descriptor = descriptor
        self.trigger_ts = trigger_ts
        self.setup_score = setup_score

    def evaluate(self, state, features, prior_event):
        if state.latest.timestamp != self.trigger_ts:
            return None
        return StrategyIntent(
            descriptor=self.descriptor,
            symbol=state.symbol,
            state=LifecycleState.FIRE,
            event_timestamp=self.trigger_ts,
            setup_anchor=self.trigger_ts,
            reference_price=state.latest.close,
            setup_score=self.setup_score,
            execution_score=80.0,
            reason_codes=(self.descriptor.variant_id,),
            explanation="fixed test edge",
            entry_trigger=state.latest.close,
        )


def _fixed_descriptor(strategy_id, variant, direction, group):
    return StrategyDescriptor(
        strategy_id=strategy_id,
        strategy_family=strategy_id,
        variant_id=variant,
        direction=direction,
        strategy_version="test-v1",
        production_status=ProductionStatus.RESEARCH,
        production_eligible=False,
        correlation_group=group,
        evidence_score=0.0,
    )


def _registry(adapters):
    rows = []
    for adapter in adapters:
        d = adapter.descriptor
        rows.append({
            "strategy_id": d.strategy_id,
            "variant_id": d.variant_id,
            "direction": d.direction.value,
            "production_eligible": True,
            "robustness_score": 0.80,
        })
    return StrategyRegistry.from_leaderboard(adapters, pd.DataFrame(rows))


def _one_bar(ts):
    return MarketBar("XYZ", ts, 10.0, 10.4, 9.9, 10.3, 50_000)


def _fixed_context(**extra):
    base = {
        "prior_close": 9.0,
        "opening_rvol": 8.0,
        "catalyst_score": 75.0,
        "catalyst_class": "NEWS",
    }
    base.update(extra)
    return base


def test_independent_multi_edge_confirms_and_scores_above_single_edge(tmp_path):
    ts = datetime(2026, 9, 2, 10, 45, tzinfo=ET)
    orb = FixedFireAdapter(_fixed_descriptor("ORB", "ORB_LONG_BREAK", Direction.LONG, "ORB"), ts)
    vwap = FixedFireAdapter(_fixed_descriptor("VWAP", "VWAP_LONG_RECLAIM", Direction.LONG, "VWAP"), ts)

    single_ledger = ForwardLedger(tmp_path / "single.db")
    single = ScannerService(_registry([orb]), single_ledger)
    single.process_bar(_one_bar(ts), _fixed_context())
    single_score = single.ranked_snapshot()[0].score
    single_ledger.close()

    multi_ledger = ForwardLedger(tmp_path / "multi.db")
    multi = ScannerService(_registry([orb, vwap]), multi_ledger)
    multi.process_bar(_one_bar(ts), _fixed_context())
    ranked = multi.ranked_snapshot()
    assert ranked[0].consensus.confidence_label == "CONFIRMED"
    assert ranked[0].score > single_score
    multi_ledger.close()


def test_opposing_edges_surface_conflict_and_penalty(tmp_path):
    ts = datetime(2026, 9, 2, 11, 0, tzinfo=ET)
    long = FixedFireAdapter(_fixed_descriptor("ORB", "ORB_LONG_BREAK", Direction.LONG, "ORB"), ts)
    short = FixedFireAdapter(_fixed_descriptor("VWAP", "VWAP_SHORT_REJECTION", Direction.SHORT, "VWAP"), ts)
    ledger = ForwardLedger(tmp_path / "conflict.db")
    service = ScannerService(_registry([long, short]), ledger)
    service.process_bar(_one_bar(ts), _fixed_context())
    ranked = service.ranked_snapshot()
    assert len(ranked) == 2
    assert all(item.consensus.conflict for item in ranked)
    assert all(item.consensus.confidence_label == "CONFLICT" for item in ranked)
    ledger.close()


def test_stale_feed_blocks_production_fire(tmp_path):
    ts = datetime(2026, 9, 2, 11, 30, tzinfo=ET)
    adapter = FixedFireAdapter(_fixed_descriptor("ORB", "ORB_LONG_BREAK", Direction.LONG, "ORB"), ts)
    ledger = ForwardLedger(tmp_path / "stale.db")
    health = FeedHealthMonitor(delayed_after_seconds=15, stale_after_seconds=90)
    service = ScannerService(_registry([adapter]), ledger, feed_health=health)
    events = service.process_bar(
        _one_bar(ts),
        _fixed_context(_scanner_now=ts + timedelta(seconds=120)),
    )
    assert len(events) == 1
    assert events[0].effective_state is LifecycleState.DATA_DEGRADED
    assert events[0].action_label == "DATA DEGRADED"
    ledger.close()


def test_restart_restore_and_replay_do_not_duplicate_fire(tmp_path):
    path = tmp_path / "restart.db"
    first_ledger = ForwardLedger(path)
    first = ScannerService(_orb_registry(True), first_ledger)
    for bar in _orb_stream():
        first.process_bar(bar, _orb_context())
    assert first_ledger.event_count() == 1
    first_ledger.close()

    reopened = ForwardLedger(path)
    second = ScannerService(
        _orb_registry(True),
        reopened,
        restore_session_date=date(2026, 8, 28),
    )
    replay_events = []
    for bar in _orb_stream():
        replay_events.extend(second.process_bar(bar, _orb_context()))
    assert replay_events == []
    assert reopened.event_count() == 1
    reopened.close()
