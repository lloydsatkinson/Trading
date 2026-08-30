import pandas as pd

from scanner.strategies.vwap_momentum.config import VWAPConfig
from scanner.strategies.vwap_momentum.strategy import generate_vwap_signals


def bars(rows):
    return pd.DataFrame([
        {
            "symbol": "AAA",
            "timestamp": pd.Timestamp(ts, tz="America/New_York").tz_convert("UTC"),
            "open": o, "high": h, "low": l, "close": c, "volume": v, "vwap": vw,
        }
        for ts, o, h, l, c, v, vw in rows
    ])


def context(**overrides):
    out = {
        "symbol": "AAA", "date": "2026-08-28", "prior_close": 4.0,
        "market_cap": 200_000_000, "pm_gap_pct": 0.15,
        "pm_dollar_turnover": 5_000_000, "opening_rvol": 6.0,
        "float_shares": 12_000_000, "catalyst_class": "NEWS", "split": "forward",
    }
    out.update(overrides)
    return out


def reclaim_fixture():
    return bars([
        ("2026-08-28 09:30", 4.50, 4.55, 4.45, 4.52, 100, 4.50),
        ("2026-08-28 09:31", 4.60, 4.80, 4.58, 4.75, 100, 4.72),
        ("2026-08-28 09:32", 4.74, 4.76, 4.50, 4.55, 100, 4.56),
        ("2026-08-28 09:33", 4.56, 4.75, 4.54, 4.72, 300, 4.69),
        ("2026-08-28 09:34", 4.73, 4.90, 4.70, 4.85, 200, 4.82),
    ])


def test_vwap_long_requires_impulse_touch_reclaim_and_next_bar_entry():
    out = generate_vwap_signals(
        reclaim_fixture(), context(),
        VWAPConfig(min_gap_pct=0.10, min_impulse_pct=0.15, min_rvol=3.0,
                   min_pm_dollar_turnover=2_000_000, min_retained_gain=0.60,
                   min_reclaim_volume_ratio=1.5),
    )
    row = out[out["variant_id"].eq("VWAP_LONG_RECLAIM")].iloc[0]
    assert row["direction"] == "LONG"
    assert str(row["signal_timestamp"])[11:16] == "09:33"
    assert str(row["entry_timestamp"])[11:16] == "09:34"
    assert row["entry_price_raw"] == 4.73
    assert row["stop_reference"] == 4.50
    assert row["market_cap_bucket"] == "MICROCAP"


def test_vwap_long_does_not_use_touch_before_impulse_as_pullback():
    fixture = reclaim_fixture()
    fixture.loc[2, "low"] = 4.68
    fixture.loc[2, "close"] = 4.69
    fixture.loc[2, "vwap"] = 4.69
    out = generate_vwap_signals(fixture, context(), VWAPConfig(min_impulse_pct=0.15))
    assert out.empty or out[out["variant_id"].eq("VWAP_LONG_RECLAIM")].empty


def test_vwap_long_rejects_insufficient_retained_gain():
    fixture = reclaim_fixture()
    fixture.loc[2, "low"] = 4.20
    fixture.loc[2, "close"] = 4.30
    fixture.loc[2, "vwap"] = 4.45
    out = generate_vwap_signals(fixture, context(), VWAPConfig(min_impulse_pct=0.15))
    assert out.empty or out[out["variant_id"].eq("VWAP_LONG_RECLAIM")].empty


def test_vwap_long_requires_reclaim_volume_confirmation():
    fixture = reclaim_fixture()
    fixture.loc[3, "volume"] = 100
    out = generate_vwap_signals(fixture, context())
    assert out.empty or out[out["variant_id"].eq("VWAP_LONG_RECLAIM")].empty


def test_vwap_rejects_known_market_cap_outside_primary_universe():
    assert generate_vwap_signals(reclaim_fixture(), context(market_cap=5_000_000)).empty


def test_vwap_short_rejection_requires_failed_reclaim_then_break():
    fixture = bars([
        ("2026-08-28 09:30", 4.50, 4.55, 4.45, 4.52, 100, 4.50),
        ("2026-08-28 09:31", 4.60, 4.90, 4.58, 4.85, 100, 4.82),
        ("2026-08-28 09:32", 4.84, 4.86, 4.50, 4.55, 120, 4.58),
        ("2026-08-28 09:33", 4.56, 4.72, 4.50, 4.58, 150, 4.62),
        ("2026-08-28 09:34", 4.57, 4.60, 4.38, 4.42, 350, 4.48),
        ("2026-08-28 09:35", 4.40, 4.45, 4.25, 4.30, 220, 4.34),
    ])
    out = generate_vwap_signals(fixture, context())
    row = out[out["variant_id"].eq("VWAP_SHORT_REJECTION")].iloc[0]
    assert row["direction"] == "SHORT"
    assert str(row["signal_timestamp"])[11:16] == "09:34"
    assert str(row["entry_timestamp"])[11:16] == "09:35"
    assert row["stop_reference"] == 4.72
    assert row["borrow_status"] == "UNKNOWN"
