from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import math
import pytest

from scanner.live.feature_engine import FeatureEngine
from scanner.live.models import MarketBar
from scanner.live.symbol_state import SymbolState, SymbolStateStore

ET = ZoneInfo("America/New_York")


def _bar(minute, open_, high, low, close, volume, symbol="ABC"):
    return MarketBar(
        symbol=symbol,
        timestamp=datetime(2026, 9, 2, 9, minute, tzinfo=ET),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


def test_symbol_state_is_bounded_and_strictly_ordered():
    state = SymbolState("ABC", max_bars=3)
    for minute in (30, 31, 32, 33):
        state.append_bar(_bar(minute, 4.0, 4.1, 3.9, 4.0, 100))

    frame = state.bars_frame()
    assert list(frame["timestamp_et"].dt.minute) == [31, 32, 33]
    assert state.latest.timestamp.minute == 33

    with pytest.raises(ValueError):
        state.append_bar(_bar(34, 4.0, 4.1, 3.9, 4.0, 100, symbol="XYZ"))
    with pytest.raises(ValueError):
        state.append_bar(MarketBar("ABC", datetime(2026, 9, 2, 9, 34), 4, 4.1, 3.9, 4, 100))
    with pytest.raises(ValueError):
        state.append_bar(_bar(33, 4.0, 4.1, 3.9, 4.0, 100))


def test_symbol_state_store_returns_one_state_per_symbol():
    store = SymbolStateStore(max_bars=5)
    assert store.get("abc") is store.get("ABC")
    assert store.get("ABC").symbol == "ABC"


def test_feature_engine_uses_only_stored_point_in_time_bars():
    state = SymbolState("ABC")
    state.append_bar(_bar(30, 4.00, 4.20, 3.95, 4.10, 100))
    state.append_bar(_bar(31, 4.10, 4.30, 4.05, 4.20, 200))
    state.append_bar(_bar(32, 4.20, 4.40, 4.15, 4.35, 400))

    snapshot = FeatureEngine().snapshot(
        state,
        {
            "prior_close": 4.0,
            "opening_rvol": 8.0,
            "market_cap": 120_000_000,
            "float_shares": 8_000_000,
            "catalyst_class": "EARNINGS",
        },
    )

    assert snapshot.timestamp.minute == 32
    assert snapshot.hod == 4.40
    assert snapshot.lod == 3.95
    assert snapshot.rvol == 8.0
    assert snapshot.catalyst_class == "EARNINGS"
    assert snapshot.market_cap_bucket == "MICROCAP"
    assert snapshot.float_bucket == "5-10M"
    assert snapshot.gap_pct == pytest.approx(4.35 / 4.0 - 1.0)
    assert snapshot.session_vwap is not None and math.isfinite(snapshot.session_vwap)
    assert snapshot.volume_acceleration == pytest.approx(400 / 150)
    assert len(state.bars_frame()) == 3
