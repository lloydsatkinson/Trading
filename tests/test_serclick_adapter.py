import pandas as pd

from scanner.strategies.serclick_leo.config import SerClickStrategyConfig
from scanner.strategies.serclick_leo.strategy import adapt_serclick_ignitions


def test_adapter_does_not_change_locked_leo_thresholds():
    cfg = SerClickStrategyConfig()
    assert cfg.extension_ratio == 1.20
    assert cfg.pm_dollar_turnover_min == 10_000_000.0
    assert cfg.open30_dollar_turnover_min == 5_000_000.0
    assert cfg.slippage_bps == 25.0


def test_serclick_midday_ignition_maps_without_repricing_entry():
    source = pd.DataFrame([{
        "symbol": "AAA", "date": "2026-08-28", "split": "forward",
        "population": "BOTH", "ignition_window": "10:30-15:00",
        "timestamp": pd.Timestamp("2026-08-28 11:00", tz="America/New_York"),
        "entry_timestamp": pd.Timestamp("2026-08-28 11:01", tz="America/New_York"),
        "entry_price_raw": 4.00, "entry_price_slipped": 4.01,
        "market_cap": 75_000_000.0, "market_cap_bucket": "MICROCAP",
    }])
    out = adapt_serclick_ignitions(source)
    row = out.iloc[0]
    assert row["strategy_id"] == "SERCLICK_LEO"
    assert row["variant_id"] == "LEO_BOTH_MIDDAY"
    assert row["entry_price_raw"] == 4.00
    assert row["entry_price_slipped"] == 4.01
    assert row["entry_timestamp"] == source.iloc[0]["entry_timestamp"]
    assert row["market_cap_bucket"] == "MICROCAP"
    assert row["direction"] == "LONG"


def test_serclick_morning_and_after_hours_are_distinct_variants():
    source = pd.DataFrame([
        {"symbol":"A","date":"2026-08-28","population":"BOTH","ignition_window":"09:30-10:30","timestamp":"2026-08-28 10:00-04:00","entry_timestamp":"2026-08-28 10:01-04:00","entry_price_raw":5.0,"entry_price_slipped":5.0125},
        {"symbol":"B","date":"2026-08-28","population":"BOTH","ignition_window":"16:00-20:00","timestamp":"2026-08-28 17:00-04:00","entry_timestamp":"2026-08-28 17:01-04:00","entry_price_raw":6.0,"entry_price_slipped":6.015},
    ])
    out = adapt_serclick_ignitions(source)
    assert list(out["variant_id"]) == ["MORNING_OBSERVATION", "LEO_BOTH_AH"]


def test_serclick_non_both_midday_remains_control_variant():
    source = pd.DataFrame([{
        "symbol":"A","date":"2026-08-28","population":"PM_ONLY","ignition_window":"10:30-15:00",
        "timestamp":"2026-08-28 11:00-04:00","entry_timestamp":"2026-08-28 11:01-04:00",
        "entry_price_raw":5.0,"entry_price_slipped":5.0125,
    }])
    out = adapt_serclick_ignitions(source)
    assert out.iloc[0]["variant_id"] == "SERCLICK_CONTROL"
