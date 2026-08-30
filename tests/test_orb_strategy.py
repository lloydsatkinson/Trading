import pandas as pd

from scanner.strategies.orb_stocks_in_play.config import ORBConfig
from scanner.strategies.orb_stocks_in_play.strategy import generate_orb_signals


def bars(rows):
    return pd.DataFrame([
        {
            "symbol": "AAA",
            "timestamp": pd.Timestamp(ts, tz="America/New_York").tz_convert("UTC"),
            "open": o, "high": h, "low": l, "close": c, "volume": v, "vwap": vw,
        }
        for ts, o, h, l, c, v, vw in rows
    ])


def valid_context(**overrides):
    ctx = {
        "symbol": "AAA", "date": "2026-08-28", "prior_close": 4.0,
        "market_cap": 150_000_000, "pm_gap_pct": 0.25,
        "pm_dollar_turnover": 5_000_000, "opening_rvol": 6.0,
        "float_shares": 8_000_000, "catalyst_class": "NEWS", "split": "forward",
    }
    ctx.update(overrides)
    return ctx


def long_breakout_fixture():
    return bars([
        ("2026-08-28 09:30", 5.00, 5.20, 4.95, 5.10, 100, 5.08),
        ("2026-08-28 09:31", 5.10, 5.30, 5.05, 5.20, 100, 5.18),
        ("2026-08-28 09:32", 5.20, 5.40, 5.15, 5.35, 100, 5.30),
        ("2026-08-28 09:33", 5.34, 5.38, 5.20, 5.25, 100, 5.28),
        ("2026-08-28 09:34", 5.25, 5.35, 5.15, 5.20, 100, 5.24),
        ("2026-08-28 09:35", 5.20, 5.36, 5.18, 5.30, 100, 5.28),
        ("2026-08-28 09:36", 5.31, 5.65, 5.30, 5.60, 300, 5.55),
        ("2026-08-28 09:37", 5.62, 5.80, 5.55, 5.75, 220, 5.70),
    ])


def test_orb_long_requires_locked_range_and_enters_next_bar():
    out = generate_orb_signals(
        long_breakout_fixture(), valid_context(),
        ORBConfig(min_gap_pct=0.10, min_pm_dollar_turnover=2_000_000,
                  min_opening_rvol=3.0, min_breakout_volume_ratio=1.5, min_clv=0.60),
    )
    row = out[out["variant_id"].eq("ORB_LONG_BREAK")].iloc[0]
    assert str(row["signal_timestamp"])[11:16] == "09:36"
    assert str(row["entry_timestamp"])[11:16] == "09:37"
    assert row["entry_price_raw"] == 5.62
    assert row["entry_price_slipped"] > row["entry_price_raw"]
    assert row["stop_reference"] == 5.30
    assert row["strategy_id"] == "ORB"
    assert row["market_cap_bucket"] == "MICROCAP"
    assert row["float_bucket"] == "5-10M"


def test_orb_wick_without_close_above_range_is_not_long_break_signal():
    fixture = long_breakout_fixture()
    fixture.loc[fixture.index[-2], "close"] = 5.35
    out = generate_orb_signals(fixture, valid_context())
    assert out.empty or out[out["variant_id"].eq("ORB_LONG_BREAK")].empty


def test_orb_rejects_known_market_cap_outside_primary_universe():
    out = generate_orb_signals(long_breakout_fixture(), valid_context(market_cap=30_000_000))
    assert out.empty


def test_orb_negative_gap_short_breaks_range_low_and_enters_next_bar():
    fixture = bars([
        ("2026-08-28 09:30", 4.00, 4.10, 3.90, 3.95, 100, 3.98),
        ("2026-08-28 09:31", 3.95, 4.00, 3.85, 3.90, 100, 3.91),
        ("2026-08-28 09:32", 3.90, 3.95, 3.80, 3.85, 100, 3.87),
        ("2026-08-28 09:33", 3.85, 3.92, 3.82, 3.88, 100, 3.87),
        ("2026-08-28 09:34", 3.88, 3.90, 3.81, 3.84, 100, 3.85),
        ("2026-08-28 09:35", 3.84, 3.87, 3.80, 3.82, 100, 3.83),
        ("2026-08-28 09:36", 3.82, 3.83, 3.55, 3.58, 300, 3.62),
        ("2026-08-28 09:37", 3.56, 3.60, 3.45, 3.50, 220, 3.53),
    ])
    out = generate_orb_signals(fixture, valid_context(pm_gap_pct=-0.20))
    row = out[out["variant_id"].eq("ORB_SHORT_NEGATIVE_GAP")].iloc[0]
    assert row["direction"] == "SHORT"
    assert row["entry_price_raw"] == 3.56
    assert row["entry_price_slipped"] < row["entry_price_raw"]
    assert row["borrow_status"] == "UNKNOWN"


def test_orb_candidate_gates_block_low_participation():
    out = generate_orb_signals(long_breakout_fixture(), valid_context(opening_rvol=1.5))
    assert out.empty


def test_orb_pullback_variant_requires_break_retest_reclaim_and_next_bar_entry():
    fixture = bars([
        ("2026-08-28 09:30", 5.00, 5.20, 4.95, 5.10, 100, 5.08),
        ("2026-08-28 09:31", 5.10, 5.30, 5.05, 5.20, 100, 5.18),
        ("2026-08-28 09:32", 5.20, 5.40, 5.15, 5.35, 100, 5.30),
        ("2026-08-28 09:33", 5.34, 5.38, 5.20, 5.25, 100, 5.28),
        ("2026-08-28 09:34", 5.25, 5.35, 5.15, 5.20, 100, 5.24),
        ("2026-08-28 09:35", 5.25, 5.60, 5.24, 5.55, 300, 5.50),
        ("2026-08-28 09:36", 5.54, 5.56, 5.38, 5.42, 120, 5.45),
        ("2026-08-28 09:37", 5.43, 5.65, 5.42, 5.62, 300, 5.58),
        ("2026-08-28 09:38", 5.63, 5.80, 5.60, 5.75, 200, 5.72),
    ])
    out = generate_orb_signals(fixture, valid_context())
    row = out[out["variant_id"].eq("ORB_LONG_PULLBACK")].iloc[0]
    assert str(row["signal_timestamp"])[11:16] == "09:37"
    assert str(row["entry_timestamp"])[11:16] == "09:38"
    assert row["stop_reference"] == 5.38


def test_orb_failed_positive_gap_reversal_short_is_separate_variant():
    fixture = bars([
        ("2026-08-28 09:30", 5.10, 5.25, 5.00, 5.15, 100, 5.13),
        ("2026-08-28 09:31", 5.15, 5.30, 5.05, 5.20, 100, 5.18),
        ("2026-08-28 09:32", 5.20, 5.40, 5.10, 5.30, 100, 5.28),
        ("2026-08-28 09:33", 5.30, 5.35, 5.10, 5.20, 100, 5.22),
        ("2026-08-28 09:34", 5.20, 5.30, 5.05, 5.15, 100, 5.18),
        ("2026-08-28 09:35", 5.20, 5.55, 5.10, 5.35, 180, 5.30),
        ("2026-08-28 09:36", 5.30, 5.32, 4.82, 4.88, 350, 4.98),
        ("2026-08-28 09:37", 4.86, 4.90, 4.65, 4.70, 240, 4.75),
    ])
    out = generate_orb_signals(fixture, valid_context(pm_gap_pct=0.20))
    row = out[out["variant_id"].eq("ORB_SHORT_FAILED_GAP")].iloc[0]
    assert row["direction"] == "SHORT"
    assert str(row["entry_timestamp"])[11:16] == "09:37"
    assert row["borrow_status"] == "UNKNOWN"
