import pandas as pd

from scanner.live.adapters.serclick_leo import SerClickLeoLiveAdapter
from scanner.live.models import (
    Direction,
    FeatureSnapshot,
    LifecycleState,
    MarketBar,
    MarketSession,
    ProductionStatus,
    StrategyDescriptor,
)
from scanner.live.symbol_state import SymbolState
from scanner.serclick.config import SerClickConfig
from scanner.serclick.features import analyze_candidate_day
from scanner.strategies.serclick_leo.strategy import serclick_variant


def _cfg():
    return SerClickConfig(
        shorts_building_drawdown=0.03,
        absorption_window_minutes=3,
        absorption_percentile=0.0,
        absorption_min_down_fraction=0.0,
        absorption_max_new_low_extension=1.0,
        absorption_min_down_dollar=0.0,
        absorption_memory_minutes=60,
        armed_distance_to_pain=1.0,
        expansion_window_minutes=3,
        expansion_percentile=0.0,
        expansion_min_up_displacement=0.0,
        expansion_min_buy_dollar=0.0,
        acceleration_min_return_3m=-1.0,
    )


def _qualification():
    return {
        "population": "BOTH",
        "leo_pm_pass": True,
        "leo_open_pass": True,
        "discovery_time": "10:30",
    }


def _bars():
    rows = [
        ("2026-08-28 10:30", 9.80, 10.00, 9.70, 9.80, 1000),
        ("2026-08-28 10:31", 9.80, 9.82, 9.30, 9.40, 1000),
        ("2026-08-28 10:32", 9.40, 9.43, 9.30, 9.35, 1000),
        ("2026-08-28 10:33", 9.35, 9.38, 9.25, 9.30, 1000),
        ("2026-08-28 10:34", 9.30, 9.33, 9.20, 9.25, 1000),
        ("2026-08-28 10:35", 9.25, 9.28, 9.15, 9.20, 1000),
        ("2026-08-28 10:36", 9.20, 9.23, 9.10, 9.15, 1000),
        ("2026-08-28 10:37", 9.15, 9.18, 9.05, 9.10, 1000),
        ("2026-08-28 10:38", 9.10, 9.13, 9.00, 9.05, 1000),
        ("2026-08-28 10:39", 9.05, 9.08, 8.95, 9.00, 1000),
        ("2026-08-28 10:40", 9.00, 9.03, 8.90, 8.95, 1000),
        ("2026-08-28 10:41", 8.95, 8.98, 8.85, 8.90, 1000),
        ("2026-08-28 10:42", 8.90, 8.93, 8.83, 8.88, 1000),
        ("2026-08-28 10:43", 8.88, 8.91, 8.81, 8.86, 1000),
        ("2026-08-28 10:44", 8.86, 8.93, 8.84, 8.90, 1000),
        ("2026-08-28 10:45", 8.90, 9.50, 8.85, 9.40, 5000),
        ("2026-08-28 10:46", 9.40, 9.45, 9.20, 9.30, 1000),
    ]
    return pd.DataFrame([
        {
            "symbol": "AAA",
            "timestamp": pd.Timestamp(ts, tz="America/New_York").tz_convert("UTC"),
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "trade_count": 10,
            "vwap": close,
        }
        for ts, open_, high, low, close, volume in rows
    ])


def _descriptor():
    return StrategyDescriptor(
        strategy_id="SERCLICK_LEO",
        strategy_family="SERCLICK_LEO",
        variant_id="LEO_BOTH_MIDDAY",
        direction=Direction.LONG,
        strategy_version="serclick-v1",
        production_status=ProductionStatus.RESEARCH,
        production_eligible=False,
        correlation_group="SERCLICK_LEO",
        evidence_score=0.0,
    )


def _market_bar(row):
    ts = pd.Timestamp(row["timestamp"]).tz_convert("America/New_York").to_pydatetime()
    return MarketBar("AAA", ts, row["open"], row["high"], row["low"], row["close"], row["volume"])


def _features(bar):
    return FeatureSnapshot(
        symbol="AAA",
        timestamp=bar.timestamp,
        session=MarketSession.REGULAR,
        last_price=bar.close,
        context=_qualification(),
    )


def test_serclick_live_ignition_matches_first_prefix_transition():
    full = _bars()
    transitions, _ = analyze_candidate_day(full, _qualification(), _cfg())
    ignition = transitions[transitions["state"].eq("IGNITION")]
    assert not ignition.empty, transitions.to_dict("records")
    truth_ts = pd.Timestamp(ignition.iloc[0]["timestamp"])

    adapter = SerClickLeoLiveAdapter(_descriptor(), _cfg())
    state = SymbolState("AAA")
    fires = []
    for _, row in full.iterrows():
        bar = _market_bar(row)
        state.append_bar(bar)
        intent = adapter.evaluate(state, _features(bar), None)
        if intent is not None and intent.state is LifecycleState.FIRE:
            fires.append(intent)

    assert len(fires) == 1
    assert pd.Timestamp(fires[0].event_timestamp) == truth_ts
    assert fires[0].descriptor.variant_id == "LEO_BOTH_MIDDAY"
    assert fires[0].descriptor.direction is Direction.LONG


def test_serclick_variant_normalization_is_shared_with_batch_adapter():
    assert serclick_variant("BOTH", "09:30-10:30") == "MORNING_OBSERVATION"
    assert serclick_variant("BOTH", "10:30-15:00") == "LEO_BOTH_MIDDAY"
    assert serclick_variant("BOTH", "16:00-20:00") == "LEO_BOTH_AH"
