import pandas as pd

from scanner.strategies.merciless_q.config import MercilessConfig
from scanner.strategies.merciless_q.strategy import generate_merciless_signals


def bars(rows):
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


def context(**overrides):
    out = {
        "symbol": "AAA",
        "date": "2026-08-28",
        "prior_close": 4.0,
        "market_cap": 200_000_000,
        "pm_gap_pct": 0.15,
        "pm_dollar_turnover": 5_000_000,
        "opening_rvol": 6.0,
        "float_shares": 12_000_000,
        "catalyst_class": "NEWS",
        "split": "forward",
    }
    out.update(overrides)
    return out


def first_pullback_fixture():
    return bars([
        ("2026-08-28 09:30", 4.45, 4.55, 4.42, 4.52, 100, 4.49),
        ("2026-08-28 09:31", 4.52, 4.90, 4.50, 4.86, 300, 4.71),
        ("2026-08-28 09:32", 4.84, 4.88, 4.70, 4.76, 180, 4.74),
        ("2026-08-28 09:33", 4.75, 4.79, 4.68, 4.73, 120, 4.73),
        ("2026-08-28 09:34", 4.73, 4.78, 4.70, 4.76, 90, 4.74),
        ("2026-08-28 09:35", 4.76, 4.91, 4.75, 4.89, 300, 4.84),
        ("2026-08-28 09:36", 4.90, 5.05, 4.88, 5.00, 220, 4.96),
    ])


def test_merciless_requires_minimum_impulse():
    fixture = first_pullback_fixture().copy()
    fixture.loc[1, ["open", "high", "low", "close", "vwap"]] = [4.45, 4.55, 4.44, 4.52, 4.50]
    out = generate_merciless_signals(
        fixture,
        context(),
        MercilessConfig(min_impulse_pct=0.20),
    )
    assert out.empty


def test_first_pullback_waits_for_contraction_and_uses_next_bar_entry():
    out = generate_merciless_signals(
        first_pullback_fixture(),
        context(),
        MercilessConfig(
            min_impulse_pct=0.15,
            min_contraction_bars=2,
            max_contraction_bars=5,
            min_breakout_volume_ratio=1.50,
        ),
    )
    row = out[out["variant_id"].eq("MMQ_FIRST_PULLBACK")].iloc[0]
    assert row["direction"] == "LONG"
    assert str(row["signal_timestamp"])[11:16] == "09:35"
    assert str(row["entry_timestamp"])[11:16] == "09:36"
    assert row["entry_price_raw"] == 4.90
    assert row["stop_reference"] == 4.68
    assert row["sequence_number"] == 1
    assert 0.0 <= row["mmq_score"] <= 100.0
    assert row["setup_metadata"]["retained_gain"] >= 0.55


def test_first_pullback_rejects_excessive_upper_wick_on_trigger():
    fixture = first_pullback_fixture().copy()
    fixture.loc[5, ["high", "close"]] = [5.10, 4.82]
    out = generate_merciless_signals(
        fixture,
        context(),
        MercilessConfig(min_impulse_pct=0.15, max_upper_wick_ratio=0.40),
    )
    assert out.empty or out[out["variant_id"].eq("MMQ_FIRST_PULLBACK")].empty
