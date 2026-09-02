from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from scanner.live.adapters.orb import ORBLiveAdapter
from scanner.live.feature_engine import FeatureEngine
from scanner.live.models import Direction, LifecycleState, ProductionStatus, StrategyDescriptor, MarketBar
from scanner.live.symbol_state import SymbolState
from scanner.strategies.orb_stocks_in_play.config import ORBConfig
from scanner.strategies.orb_stocks_in_play.strategy import generate_orb_signals

ET = ZoneInfo("America/New_York")


def _bars():
    rows = [
        ("2026-08-28 09:30", 5.00, 5.20, 4.95, 5.10, 100, 5.08),
        ("2026-08-28 09:31", 5.10, 5.30, 5.05, 5.20, 100, 5.18),
        ("2026-08-28 09:32", 5.20, 5.40, 5.15, 5.35, 100, 5.30),
        ("2026-08-28 09:33", 5.34, 5.38, 5.20, 5.25, 100, 5.28),
        ("2026-08-28 09:34", 5.25, 5.35, 5.15, 5.20, 100, 5.24),
        ("2026-08-28 09:35", 5.20, 5.36, 5.18, 5.30, 100, 5.28),
        ("2026-08-28 09:36", 5.31, 5.65, 5.30, 5.60, 300, 5.55),
        ("2026-08-28 09:37", 5.62, 5.80, 5.55, 5.75, 220, 5.70),
    ]
    return pd.DataFrame([
        {
            "symbol": "AAA",
            "timestamp": pd.Timestamp(ts, tz="America/New_York").tz_convert("UTC"),
            "open": o,
            "high": h,
            "low": l,
            "close": c,
            "volume": v,
            "vwap": vw,
        }
        for ts, o, h, l, c, v, vw in rows
    ])


def _context():
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
        "split": "forward",
    }


def _descriptor():
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


def _market_bar(row):
    ts = pd.Timestamp(row["timestamp"]).tz_convert("America/New_York").to_pydatetime()
    return MarketBar("AAA", ts, row["open"], row["high"], row["low"], row["close"], row["volume"])


def test_orb_live_prefix_fires_on_same_completed_signal_bar_as_batch_truth():
    cfg = ORBConfig(
        min_gap_pct=0.10,
        min_pm_dollar_turnover=2_000_000,
        min_opening_rvol=3.0,
        min_breakout_volume_ratio=1.5,
        min_clv=0.60,
    )
    full = _bars()
    batch = generate_orb_signals(full, _context(), cfg)
    truth = batch[batch["variant_id"].eq("ORB_LONG_BREAK")].iloc[0]

    adapter = ORBLiveAdapter(_descriptor(), cfg)
    state = SymbolState("AAA")
    engine = FeatureEngine()
    fires = []
    for _, row in full.iterrows():
        state.append_bar(_market_bar(row))
        features = engine.snapshot(state, _context())
        intent = adapter.evaluate(state, features, None)
        if intent is not None and intent.state is LifecycleState.FIRE:
            fires.append(intent)

    assert len(fires) == 1
    fire = fires[0]
    assert pd.Timestamp(fire.event_timestamp) == pd.Timestamp(truth["signal_timestamp"])
    assert fire.descriptor.variant_id == truth["variant_id"]
    assert fire.descriptor.direction.value == truth["direction"]
    assert fire.stop_reference == truth["stop_reference"] == 5.30
    assert fire.event_timestamp < datetime(2026, 8, 28, 9, 37, tzinfo=ET)
