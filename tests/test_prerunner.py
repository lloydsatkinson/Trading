import pandas as pd
import pytest

from trading_lab.prerunner import (
    ExecutionRule,
    build_snapshots,
    label_snapshot,
    simulate_snapshot_trade,
)

NY = "America/New_York"


def _row(ts, o, h, l, c, v, previous_close=10.0, ticker="TEST"):
    return {
        "timestamp": pd.Timestamp(ts, tz=NY).tz_convert("UTC"),
        "ticker": ticker,
        "open": o,
        "high": h,
        "low": l,
        "close": c,
        "volume": v,
        "previous_close": previous_close,
    }


def _current_day(late_volume=100):
    return pd.DataFrame([
        _row("2026-08-10 09:20", 9.9, 10.1, 9.8, 10.0, 80),
        _row("2026-08-10 09:29", 10.0, 10.2, 9.9, 10.1, 120),
        _row("2026-08-10 09:30", 10.1, 10.4, 10.0, 10.3, 150),
        _row("2026-08-10 09:31", 10.3, 10.6, 10.2, 10.5, 150),
        _row("2026-08-10 09:32", 10.5, 10.7, 10.4, 10.6, 100),
        _row("2026-08-10 09:33", 10.6, 10.8, 10.5, 10.7, 100),
        _row("2026-08-10 09:34", 10.7, 10.9, 10.6, 10.8, 100),
        _row("2026-08-10 09:35", 10.8, 14.0, 10.7, 13.5, late_volume),
    ])


def _history():
    return pd.DataFrame([
        _row("2026-08-06 09:30", 10, 10, 10, 10, 100),
        _row("2026-08-06 09:31", 10, 10, 10, 10, 100),
        _row("2026-08-07 09:30", 10, 10, 10, 10, 200),
        _row("2026-08-07 09:31", 10, 10, 10, 10, 200),
    ])


def test_0931_snapshot_cannot_see_0935_spike():
    a = build_snapshots(_current_day(100), _history(), freeze_times=("09:31",))
    b = build_snapshots(_current_day(10_000_000), _history(), freeze_times=("09:31",))
    cols = [
        "snapshot_price",
        "open_cum_volume",
        "open_rvol",
        "hod_extension_pct",
        "vwap_distance_pct",
        "volume_accel",
    ]
    assert a[cols].iloc[0].to_dict() == b[cols].iloc[0].to_dict()


def test_open_rvol_uses_exact_elapsed_window():
    snap = build_snapshots(_current_day(), _history(), freeze_times=("09:31",)).iloc[0]
    # Current 09:30-09:31 volume = 300. Historical cumulative windows = 200 and 400.
    assert snap.open_cum_volume == pytest.approx(300)
    assert snap.open_rvol == pytest.approx(1.0)


def test_snapshot_labels_both_long_and_short_future_path():
    bars = pd.DataFrame([
        _row("2026-08-10 09:31", 10, 10.1, 9.9, 10, 100),
        _row("2026-08-10 09:32", 10, 12, 9.5, 11, 100),
        _row("2026-08-10 09:33", 11, 13, 8, 12, 100),
    ])
    y = label_snapshot(bars, pd.Timestamp("2026-08-10 09:31", tz=NY), thresholds=(0.10, 0.20, 0.30))
    assert y["entry_price"] == pytest.approx(10.0)
    assert y["long_mfe_pct"] == pytest.approx(0.30)
    assert y["long_mae_pct"] == pytest.approx(0.20)
    assert y["short_mfe_pct"] == pytest.approx(0.20)
    assert y["short_mae_pct"] == pytest.approx(0.30)
    assert y["long_reach_20"] is True
    assert y["short_reach_20"] is True


def test_long_same_minute_stop_and_target_is_stop_first():
    bars = pd.DataFrame([
        _row("2026-08-10 09:30", 10, 10, 10, 10, 100),
        _row("2026-08-10 09:31", 10, 11.2, 9.4, 10.5, 100),
    ])
    rule = ExecutionRule(stop_pct=0.05, target_pct=0.10, max_hold_minutes=10, slippage_bps=0)
    t = simulate_snapshot_trade(bars, pd.Timestamp("2026-08-10 09:30", tz=NY), "LONG", rule)
    assert t.exit_reason == "STOP_SAME_BAR"
    assert t.return_pct == pytest.approx(-0.05)


def test_short_same_minute_stop_and_target_is_stop_first():
    bars = pd.DataFrame([
        _row("2026-08-10 09:30", 10, 10, 10, 10, 100),
        _row("2026-08-10 09:31", 10, 10.6, 8.9, 9.5, 100),
    ])
    rule = ExecutionRule(stop_pct=0.05, target_pct=0.10, max_hold_minutes=10, slippage_bps=0)
    t = simulate_snapshot_trade(bars, pd.Timestamp("2026-08-10 09:30", tz=NY), "SHORT", rule)
    assert t.exit_reason == "STOP_SAME_BAR"
    assert t.return_pct == pytest.approx(-0.05)


def test_gap_through_long_stop_uses_adverse_reopen_not_stop_price():
    bars = pd.DataFrame([
        _row("2026-08-10 09:30", 10, 10, 10, 10, 100),
        _row("2026-08-10 09:31", 10, 10.2, 9.9, 10.1, 100),
        # 09:32 missing: suspected halt/data gap. Reopens below 5% stop at 9.5.
        _row("2026-08-10 09:33", 9.0, 9.2, 8.8, 9.0, 100),
    ])
    rule = ExecutionRule(stop_pct=0.05, target_pct=0.20, max_hold_minutes=10, slippage_bps=0)
    t = simulate_snapshot_trade(bars, pd.Timestamp("2026-08-10 09:30", tz=NY), "LONG", rule)
    assert t.exit_reason == "GAP_STOP"
    assert t.exit_price == pytest.approx(9.0)
    assert t.return_pct == pytest.approx(-0.10)
