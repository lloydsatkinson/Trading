from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from scanner.live.forward_ledger import ForwardLedger
from scanner.live.models import (
    Direction,
    FeedHealth,
    LifecycleState,
    ProductionStatus,
    StrategyDescriptor,
    StrategyIntent,
)
from scanner.live.recovery import GapReconciler
from scanner.live.service import ScannerService
from scanner.live.strategy_registry import StrategyRegistry

UTC = timezone.utc


class CaptureBus:
    def __init__(self):
        self.published = []

    def publish(self, event):
        self.published.append(event)
        return True


class GapFireAdapter:
    def __init__(self):
        self.descriptor = StrategyDescriptor(
            strategy_id="GAP_TEST",
            strategy_family="GAP_TEST",
            variant_id="GAP_FIRE",
            direction=Direction.LONG,
            strategy_version="v1",
            production_status=ProductionStatus.PRODUCTION_ELIGIBLE,
            production_eligible=True,
            correlation_group="GAP_TEST",
            evidence_score=80.0,
        )

    def evaluate(self, state, features, prior_event):
        if state.latest.close < 2.20:
            return None
        ts = state.latest.timestamp
        return StrategyIntent(
            descriptor=self.descriptor,
            symbol=state.symbol,
            state=LifecycleState.FIRE,
            event_timestamp=ts,
            setup_anchor=ts,
            reference_price=state.latest.close,
            setup_score=80.0,
            execution_score=80.0,
            reason_codes=("GAP_TEST",),
            explanation="synthetic causal trigger during recovery gap",
        )


class FakeRest:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def stock_bars(self, symbols, timeframe, start, end, feed="sip", adjustment="raw", limit=10_000):
        self.calls.append((tuple(symbols), timeframe, start, end, feed))
        return pd.DataFrame(self.rows)


def rows():
    def row(ts, close):
        return {
            "symbol": "ABC",
            "timestamp": pd.Timestamp(ts),
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "volume": 1000,
        }

    return [
        row("2026-09-02T14:30:00Z", 2.00),  # start boundary: excluded
        row("2026-09-02T14:31:00Z", 2.05),
        row("2026-09-02T14:32:00Z", 2.30),  # causal FIRE inside gap
        row("2026-09-02T14:33:00Z", 2.40),  # end boundary: excluded
    ]


def build(tmp_path):
    bus = CaptureBus()
    ledger = ForwardLedger(tmp_path / "recovery.db")
    service = ScannerService(
        StrategyRegistry([GapFireAdapter()]),
        ledger,
        signal_bus=bus,
    )
    service.feed_health.begin_recovery()
    rest = FakeRest(rows())
    reconciler = GapReconciler(rest, service, feed="sip")
    return service, ledger, bus, rest, reconciler


def test_gap_trigger_is_diagnostic_not_live_fire(tmp_path):
    service, ledger, bus, rest, reconciler = build(tmp_path)
    t0 = datetime(2026, 9, 2, 14, 30, tzinfo=UTC)
    t3 = datetime(2026, 9, 2, 14, 33, tzinfo=UTC)

    out = reconciler.recover({"ABC"}, t0, t3, lambda bar: {"prior_close": 2.0})

    assert len(out) == 1
    assert out[0].reason == "MISSED_DURING_GAP"
    assert out[0].trigger_timestamp == datetime(2026, 9, 2, 14, 32, tzinfo=UTC)
    assert bus.published == []
    assert ledger.event_count() == 0
    assert ledger.gap_diagnostic_count() == 1
    assert service.feed_health.state is FeedHealth.RECOVERING
    assert len(service.states.get("ABC").bars_frame()) == 2
    assert rest.calls[0][1] == "1Min"
    ledger.close()


def test_repeating_same_recovery_is_idempotent(tmp_path):
    service, ledger, bus, _, reconciler = build(tmp_path)
    t0 = datetime(2026, 9, 2, 14, 30, tzinfo=UTC)
    t3 = datetime(2026, 9, 2, 14, 33, tzinfo=UTC)

    first = reconciler.recover({"ABC"}, t0, t3, lambda bar: {"prior_close": 2.0})
    second = reconciler.recover({"ABC"}, t0, t3, lambda bar: {"prior_close": 2.0})

    assert len(first) == 1
    assert second == []
    assert ledger.gap_diagnostic_count() == 1
    assert ledger.event_count() == 0
    assert bus.published == []
    ledger.close()


def test_gap_diagnostics_can_be_loaded_by_session_date(tmp_path):
    _, ledger, _, _, reconciler = build(tmp_path)
    t0 = datetime(2026, 9, 2, 14, 30, tzinfo=UTC)
    t3 = datetime(2026, 9, 2, 14, 33, tzinfo=UTC)
    reconciler.recover({"ABC"}, t0, t3, lambda bar: {"prior_close": 2.0})

    saved = ledger.gap_diagnostics(datetime(2026, 9, 2, tzinfo=UTC).date())
    assert len(saved) == 1
    assert saved[0].symbol == "ABC"
    assert saved[0].strategy_id == "GAP_TEST"
    ledger.close()
