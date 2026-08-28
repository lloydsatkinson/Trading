import math

import pandas as pd

from scanner.serclick.marketcap import classify_market_cap, enrich_market_caps, parse_market_cap


def test_parse_market_cap_handles_numeric_and_suffix_values():
    assert parse_market_cap(125_000_000) == 125_000_000.0
    assert parse_market_cap("$125.5M") == 125_500_000.0
    assert parse_market_cap("1.2B") == 1_200_000_000.0
    assert parse_market_cap("1,234,567") == 1_234_567.0
    assert math.isnan(parse_market_cap("N/A"))


def test_market_cap_buckets_use_locked_boundaries():
    assert classify_market_cap(299_999_999) == "MICROCAP"
    assert classify_market_cap(300_000_000) == "SMALL_CAP"
    assert classify_market_cap(1_999_999_999) == "SMALL_CAP"
    assert classify_market_cap(2_000_000_000) == "LARGER"
    assert classify_market_cap(float("nan")) == "UNKNOWN"


def test_enrichment_adds_market_cap_bucket_without_dropping_symbols():
    signals = pd.DataFrame([
        {"symbol": "AAA", "action": "WATCH"},
        {"symbol": "BBB", "action": "NO_ACTION"},
    ])
    snapshot = pd.DataFrame([
        {"symbol": "AAA", "market_cap": 75_000_000.0, "market_cap_source": "NASDAQ", "market_cap_asof": "2026-08-28"},
    ])

    out = enrich_market_caps(signals, snapshot)

    aaa = out[out["symbol"].eq("AAA")].iloc[0]
    bbb = out[out["symbol"].eq("BBB")].iloc[0]
    assert aaa["market_cap_bucket"] == "MICROCAP"
    assert bool(aaa["is_microcap"]) is True
    assert bbb["market_cap_bucket"] == "UNKNOWN"
    assert bool(bbb["is_microcap"]) is False
