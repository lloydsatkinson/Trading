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


def no_impulse_fixture():
    return bars([
        ("2026-08-28 09:30", 4.20, 4.30, 4.18, 4.26, 100, 4.24),
        ("2026-08-28 09:31", 4.26, 4.45, 4.24, 4.40, 220, 4.35),
        ("2026-08-28 09:32", 4.39, 4.50, 4.32, 4.38, 160, 4.40),
        ("2026-08-28 09:33", 4.38, 4.44, 4.31, 4.35, 120, 4.37),
        ("2026-08-28 09:34", 4.35, 4.43, 4.33, 4.40, 100, 4.38),
        ("2026-08-28 09:35", 4.40, 4.55, 4.39, 4.52, 260, 4.47),
        ("2026-08-28 09:36", 4.53, 4.62, 4.50, 4.58, 180, 4.56),
    ])


def flat_top_fixture():
    return bars([
        ("2026-08-28 09:30", 4.45, 4.58, 4.42, 4.54, 120, 4.50),
        ("2026-08-28 09:31", 4.54, 4.92, 4.52, 4.88, 360, 4.75),
        ("2026-08-28 09:32", 4.86, 4.94, 4.78, 4.90, 150, 4.87),
        ("2026-08-28 09:33", 4.88, 4.93, 4.80, 4.89, 120, 4.87),
        ("2026-08-28 09:34", 4.87, 4.94, 4.82, 4.91, 110, 4.89),
        ("2026-08-28 09:35", 4.91, 5.02, 4.90, 5.00, 300, 4.97),
        ("2026-08-28 09:36", 5.01, 5.15, 4.99, 5.10, 230, 5.07),
    ])


def vwap_reset_fixture():
    return bars([
        ("2026-08-28 09:30", 4.45, 4.56, 4.42, 4.52, 120, 4.50),
        ("2026-08-28 09:31", 4.52, 5.00, 4.50, 4.95, 420, 4.78),
        ("2026-08-28 09:32", 4.94, 4.96, 4.72, 4.78, 180, 4.82),
        ("2026-08-28 09:33", 4.78, 4.82, 4.61, 4.66, 130, 4.73),
        ("2026-08-28 09:34", 4.66, 4.84, 4.64, 4.82, 270, 4.77),
        ("2026-08-28 09:35", 4.83, 4.98, 4.81, 4.94, 220, 4.91),
    ])


def trap_fixture():
    return bars([
        ("2026-08-28 09:30", 4.45, 4.58, 4.42, 4.54, 120, 4.50),
        ("2026-08-28 09:31", 4.54, 5.00, 4.52, 4.94, 400, 4.78),
        ("2026-08-28 09:32", 4.92, 4.95, 4.74, 4.80, 170, 4.84),
        ("2026-08-28 09:33", 4.79, 4.84, 4.68, 4.73, 130, 4.76),
        ("2026-08-28 09:34", 4.72, 4.74, 4.55, 4.63, 260, 4.65),
        ("2026-08-28 09:35", 4.62, 4.83, 4.60, 4.81, 330, 4.75),
        ("2026-08-28 09:36", 4.82, 4.96, 4.80, 4.92, 210, 4.89),
    ])


def test_merciless_requires_minimum_impulse():
    out = generate_merciless_signals(
        no_impulse_fixture(),
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


def test_micro_breakout_requires_repeated_resistance_tests():
    out = generate_merciless_signals(
        flat_top_fixture(), context(), MercilessConfig(min_impulse_pct=0.15)
    )
    row = out[out["variant_id"].eq("MMQ_MICRO_BREAKOUT")].iloc[0]
    assert row["setup_metadata"]["resistance_tests"] >= 2
    assert str(row["signal_timestamp"])[11:16] == "09:35"
    assert str(row["entry_timestamp"])[11:16] == "09:36"


def test_micro_breakout_rejects_wicky_breakout():
    fixture = flat_top_fixture().copy()
    fixture.loc[5, ["high", "close"]] = [5.18, 4.96]
    out = generate_merciless_signals(
        fixture,
        context(),
        MercilessConfig(min_impulse_pct=0.15, max_upper_wick_ratio=0.40),
    )
    assert out.empty or out[out["variant_id"].eq("MMQ_MICRO_BREAKOUT")].empty


def test_vwap_reset_requires_touch_then_completed_reclaim():
    out = generate_merciless_signals(
        vwap_reset_fixture(),
        context(),
        MercilessConfig(min_impulse_pct=0.15, min_breakout_volume_ratio=1.20),
    )
    row = out[out["variant_id"].eq("MMQ_VWAP_RESET")].iloc[0]
    assert str(row["signal_timestamp"])[11:16] == "09:34"
    assert str(row["entry_timestamp"])[11:16] == "09:35"
    assert row["setup_metadata"]["vwap_touch_timestamp"] is not None


def test_trap_reclaim_requires_failed_downside_break_and_reclaim():
    out = generate_merciless_signals(
        trap_fixture(),
        context(),
        MercilessConfig(min_impulse_pct=0.15, min_breakout_volume_ratio=1.20),
    )
    row = out[out["variant_id"].eq("MMQ_TRAP_RECLAIM")].iloc[0]
    assert str(row["signal_timestamp"])[11:16] == "09:35"
    assert str(row["entry_timestamp"])[11:16] == "09:36"
    assert row["stop_reference"] == 4.55
