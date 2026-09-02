import pandas as pd
import pytest

from scanner.live.adapters.vwap import VWAPLiveAdapter
from scanner.live.feature_engine import FeatureEngine
from scanner.live.models import Direction, LifecycleState, MarketBar, ProductionStatus, StrategyDescriptor
from scanner.live.symbol_state import SymbolState
from scanner.strategies.vwap_momentum.config import VWAPConfig
from scanner.strategies.vwap_momentum.strategy import generate_vwap_signals


def _bars(rows):
    return pd.DataFrame([
        {
            "symbol": "AAA",
            "timestamp": pd.Timestamp(ts, tz="America/New_York").tz_convert("UTC"),
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "vwap": vwap,
        }
        for ts, open_, high, low, close, volume, vwap in rows
    ])


def _long_bars():
    return _bars([
        ("2026-08-28 09:30", 4.50, 4.55, 4.45, 4.52, 100, 4.50),
        ("2026-08-28 09:31", 4.60, 4.80, 4.58, 4.75, 100, 4.72),
        ("2026-08-28 09:32", 4.74, 4.76, 4.50, 4.55, 100, 4.56),
        ("2026-08-28 09:33", 4.56, 4.75, 4.54, 4.72, 300, 4.69),
        ("2026-08-28 09:34", 4.73, 4.90, 4.70, 4.85, 200, 4.82),
    ])


def _short_bars():
    return _bars([
        ("2026-08-28 09:30", 4.50, 4.55, 4.45, 4.52, 100, 4.50),
        ("2026-08-28 09:31", 4.60, 4.90, 4.58, 4.85, 100, 4.82),
        ("2026-08-28 09:32", 4.84, 4.86, 4.50, 4.55, 120, 4.58),
        ("2026-08-28 09:33", 4.56, 4.72, 4.50, 4.58, 150, 4.62),
        ("2026-08-28 09:34", 4.57, 4.60, 4.38, 4.42, 350, 4.48),
        ("2026-08-28 09:35", 4.40, 4.45, 4.25, 4.30, 220, 4.34),
    ])


def _context():
    return {
        "symbol": "AAA",
        "date": "2026-08-28",
        "split": "validation",
        "feed": "SIP",
        "prior_close": 4.0,
        "market_cap": 200_000_000.0,
        "pm_gap_pct": 0.15,
        "pm_dollar_turnover": 5_000_000.0,
        "opening_rvol": 6.0,
        "float_shares": 12_000_000.0,
        "catalyst_class": "NEWS",
    }


def _descriptor(variant, direction):
    return StrategyDescriptor(
        strategy_id="VWAP",
        strategy_family="VWAP",
        variant_id=variant,
        direction=direction,
        strategy_version="vwap-v1",
        production_status=ProductionStatus.RESEARCH,
        production_eligible=False,
        correlation_group="VWAP",
        evidence_score=0.0,
    )


def _market_bar(row):
    ts = pd.Timestamp(row["timestamp"]).tz_convert("America/New_York").to_pydatetime()
    return MarketBar("AAA", ts, row["open"], row["high"], row["low"], row["close"], row["volume"])


@pytest.mark.parametrize(
    ("fixture", "variant", "direction"),
    [
        (_long_bars, "VWAP_LONG_RECLAIM", Direction.LONG),
        (_short_bars, "VWAP_SHORT_REJECTION", Direction.SHORT),
    ],
)
def test_vwap_live_prefix_matches_batch_trigger_and_structural_stop(fixture, variant, direction):
    cfg = VWAPConfig()
    full = fixture()
    batch = generate_vwap_signals(full, _context(), cfg)
    truth = batch[batch["variant_id"].eq(variant)].iloc[0]

    adapter = VWAPLiveAdapter(_descriptor(variant, direction), cfg)
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
    assert fire.descriptor.variant_id == variant
    assert fire.descriptor.direction is direction
    assert fire.stop_reference == pytest.approx(float(truth["stop_reference"]))
