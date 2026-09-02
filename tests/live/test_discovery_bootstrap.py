from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd

from scanner.live.bootstrap import SessionBootstrap
from scanner.live.discovery import DiscoveryGate
from scanner.live.forward_ledger import ForwardLedger
from scanner.live.models import (
    Direction,
    LifecycleState,
    MarketBar,
    MarketLuld,
    MarketQuote,
    MarketStatus,
    ProductionStatus,
    StrategyDescriptor,
    StrategyIntent,
)
from scanner.live.service import ScannerService
from scanner.live.status_book import StatusBook
from scanner.live.strategy_registry import StrategyRegistry
from scanner.live.symbol_state import SymbolState

ET = ZoneInfo("America/New_York")
UTC = timezone.utc


def bar(symbol: str, hm: str, close: float, volume: float, day: str = "2026-09-02") -> MarketBar:
    ts = datetime.fromisoformat(f"{day}T{hm}:00").replace(tzinfo=ET)
    return MarketBar(symbol, ts, close, close, close, close, volume)


def test_gap_activity_promotes_once():
    gate = DiscoveryGate({"ABC": 2.0})
    first = gate.observe(bar("ABC", "08:00", 2.08, 100_000))
    second = gate.observe(bar("ABC", "08:01", 2.20, 500_000))
    third = gate.observe(bar("ABC", "08:02", 2.22, 10_000))

    assert first.promoted is False
    assert second.promoted is True
    assert second.newly_promoted is True
    assert "GAP_ACTIVITY" in second.reason_codes
    assert third.promoted is True
    assert third.newly_promoted is False


def test_leo_extension_can_promote_with_meaningful_activity():
    gate = DiscoveryGate({"ABC": 2.0})
    decision = gate.observe(bar("ABC", "09:40", 2.50, 500_000))
    assert decision.promoted is True
    assert "LEO_EXTENSION" in decision.reason_codes


def test_broad_gap_rule_respects_locked_price_band():
    gate = DiscoveryGate({"PENNY": 0.80})
    decision = gate.observe(bar("PENNY", "08:00", 0.90, 2_000_000))
    assert "GAP_ACTIVITY" not in decision.reason_codes


class FakeRest:
    def __init__(self):
        self.stock_calls: list[dict] = []

    def assets(self, include_inactive=True):
        return pd.DataFrame(
            [
                {"symbol": "AAA", "status": "active", "asset_class": "us_equity", "exchange": "NASDAQ"},
                {"symbol": "BBB", "status": "inactive", "asset_class": "us_equity", "exchange": "NYSE"},
                {"symbol": "BTCUSD", "status": "active", "asset_class": "crypto", "exchange": "CRYPTO"},
            ]
        )

    def calendar(self, start: str, end: str):
        return pd.DataFrame({"date": [date(2026, 8, 31), date(2026, 9, 1), date(2026, 9, 2)]})

    def stock_bars(self, symbols, timeframe, start, end, feed="sip", adjustment="raw", limit=10_000):
        symbols = list(symbols)
        self.stock_calls.append({"symbols": symbols, "timeframe": timeframe, "start": start, "end": end, "feed": feed})
        if timeframe == "1Day":
            return pd.DataFrame(
                [
                    {"symbol": "AAA", "timestamp": pd.Timestamp("2026-09-01T04:00:00Z"), "open": 2.0, "high": 2.2, "low": 1.9, "close": 2.10, "volume": 1000},
                    {"symbol": "AAA", "timestamp": pd.Timestamp("2026-09-02T04:00:00Z"), "open": 9.0, "high": 9.0, "low": 9.0, "close": 9.0, "volume": 1},
                ]
            )
        return pd.DataFrame(
            [
                {"symbol": "AAA", "timestamp": pd.Timestamp("2026-09-02T12:01:00Z"), "open": 2.1, "high": 2.2, "low": 2.0, "close": 2.15, "volume": 200},
                {"symbol": "AAA", "timestamp": pd.Timestamp("2026-09-02T11:59:00Z"), "open": 2.0, "high": 2.1, "low": 1.9, "close": 2.05, "volume": 100},
                {"symbol": "AAA", "timestamp": pd.Timestamp("2026-09-02T12:02:00Z"), "open": 2.2, "high": 2.3, "low": 2.1, "close": 2.25, "volume": 300},
            ]
        )


def test_bootstrap_uses_active_us_equities_and_prior_session_close():
    rest = FakeRest()
    bootstrap = SessionBootstrap(rest, feed="sip")

    closes = bootstrap.load_prior_closes(date(2026, 9, 2))

    assert closes == {"AAA": 2.10}
    daily_calls = [call for call in rest.stock_calls if call["timeframe"] == "1Day"]
    assert daily_calls
    assert all(len(call["symbols"]) <= 200 for call in daily_calls)
    assert daily_calls[0]["symbols"] == ["AAA"]


def test_prime_symbol_returns_only_sorted_bars_strictly_before_current_live_bar():
    rest = FakeRest()
    bootstrap = SessionBootstrap(rest, feed="sip")
    before = datetime(2026, 9, 2, 12, 2, tzinfo=UTC)

    bars = bootstrap.prime_symbol("AAA", date(2026, 9, 2), before)

    assert [item.timestamp for item in bars] == [
        datetime(2026, 9, 2, 11, 59, tzinfo=UTC),
        datetime(2026, 9, 2, 12, 1, tzinfo=UTC),
    ]
    assert all(item.timestamp < before for item in bars)


def test_status_book_keeps_halt_and_luld_separate():
    book = StatusBook()
    ts = datetime(2026, 9, 2, 14, 35, tzinfo=UTC)
    book.update_quote(MarketQuote("ABC", ts, 1.99, 2.01, 10, 10))
    book.update_luld(MarketLuld("ABC", ts, 2.20, 1.80, "B"))

    assert round(book.spread_pct("ABC"), 4) == 0.01
    assert round(book.luld_distance_pct("ABC"), 4) == 0.10
    assert book.is_halted("ABC") is False

    book.update_status(MarketStatus("ABC", ts, True, "H", "Trading Halt"))
    assert book.is_halted("ABC") is True
    book.update_status(MarketStatus("ABC", ts, False, "T", "Trading Resumption"))
    assert book.is_halted("ABC") is False


def test_symbol_state_converts_utc_bars_to_new_york_strategy_frame():
    state = SymbolState("ABC")
    state.append_bar(MarketBar("ABC", datetime(2026, 9, 2, 13, 30, tzinfo=UTC), 2, 2, 2, 2, 100))
    frame = state.bars_frame()
    ts = frame.iloc[0]["timestamp_et"]
    assert ts.hour == 9
    assert str(ts.tzinfo) == "America/New_York"
    assert frame.iloc[0]["session_date"] == date(2026, 9, 2)


class CountingAdapter:
    def __init__(self, fire: bool = False):
        self.calls = 0
        self.fire = fire
        self.descriptor = StrategyDescriptor(
            strategy_id="TEST",
            strategy_family="TEST",
            variant_id="TEST_FIRE",
            direction=Direction.LONG,
            strategy_version="v1",
            production_status=ProductionStatus.PRODUCTION_ELIGIBLE,
            production_eligible=True,
            correlation_group="TEST",
            evidence_score=80.0,
        )

    def evaluate(self, state, features, prior_event):
        self.calls += 1
        if not self.fire:
            return None
        ts = state.latest.timestamp
        return StrategyIntent(
            descriptor=self.descriptor,
            symbol=state.symbol,
            state=LifecycleState.FIRE,
            event_timestamp=ts,
            setup_anchor=ts,
            reference_price=state.latest.close,
            setup_score=80,
            execution_score=80,
            reason_codes=("TEST",),
            explanation="test fire",
        )


def test_seed_bar_is_idempotent_and_does_not_evaluate_strategies(tmp_path):
    adapter = CountingAdapter()
    ledger = ForwardLedger(tmp_path / "seed.db")
    service = ScannerService(StrategyRegistry([adapter]), ledger)
    item = bar("ABC", "08:00", 2.1, 1000)

    assert service.seed_bar(item, {"prior_close": 2.0}) is True
    assert service.seed_bar(item, {"prior_close": 2.0}) is False
    assert adapter.calls == 0
    assert ledger.event_count() == 0
    assert len(service.states.get("ABC").bars_frame()) == 1
    ledger.close()


def test_halted_symbol_converts_production_fire_to_halted(tmp_path):
    adapter = CountingAdapter(fire=True)
    ledger = ForwardLedger(tmp_path / "halt.db")
    service = ScannerService(StrategyRegistry([adapter]), ledger)
    item = bar("ABC", "10:00", 2.2, 1000)

    emitted = service.process_bar(
        item,
        {"prior_close": 2.0, "_scanner_now": item.timestamp, "_symbol_halted": True},
    )

    assert len(emitted) == 1
    assert emitted[0].effective_state is LifecycleState.HALTED
    assert emitted[0].action_label == "HALTED"
    ledger.close()
