import math

import pandas as pd

import scanner.core.multisession_replay as multisession_replay
from scanner.core.multisession_replay import (
    SwingReplayRule,
    replay_swing_signal_grid,
    simulate_multisession_trade,
)


def bars(rows):
    return pd.DataFrame([
        {
            "symbol": "AAA",
            "timestamp": pd.Timestamp(ts, tz="America/New_York").tz_convert("UTC"),
            "open": o, "high": h, "low": l, "close": c, "volume": 100, "vwap": c,
        }
        for ts, o, h, l, c in rows
    ])


def gap_down_bars():
    return bars([
        ("2026-08-28 15:59", 10.0, 10.1, 9.9, 10.0),
        ("2026-08-31 09:30", 8.25, 8.40, 8.10, 8.30),
        ("2026-08-31 15:59", 8.50, 8.60, 8.40, 8.55),
    ])


def multi_day_bars():
    return bars([
        ("2026-08-28 15:59", 10.0, 10.1, 9.9, 10.0),
        ("2026-08-31 09:30", 10.1, 10.5, 10.0, 10.4),
        ("2026-08-31 15:59", 10.4, 10.8, 10.3, 10.7),
        ("2026-09-01 09:30", 10.8, 11.0, 10.6, 10.9),
        ("2026-09-01 15:59", 10.9, 11.2, 10.8, 11.1),
        ("2026-09-02 09:30", 11.0, 11.3, 10.9, 11.2),
        ("2026-09-02 15:59", 11.2, 11.5, 11.1, 11.4),
        ("2026-09-03 15:59", 11.4, 11.6, 11.3, 11.5),
    ])


def test_long_gap_below_stop_fills_at_first_open_not_stop_price():
    result = simulate_multisession_trade(
        gap_down_bars(),
        entry_price=10.0,
        entry_timestamp="2026-08-28 15:59-04:00",
        direction="LONG",
        rule=SwingReplayRule(stop_price=9.0, max_hold_sessions=1),
        split_end_date="2026-08-31",
        available_end_date="2026-08-31",
    )
    assert result.exit_reason == "GAP_STOP"
    assert result.exit_price == 8.25
    assert math.isclose(result.return_pct, -0.175)


def test_same_bar_stop_and_target_resolves_stop_first():
    fixture = bars([
        ("2026-08-28 15:59", 10.0, 10.0, 10.0, 10.0),
        ("2026-08-31 09:30", 10.0, 12.5, 8.5, 10.5),
        ("2026-08-31 15:59", 10.5, 10.6, 10.4, 10.5),
    ])
    result = simulate_multisession_trade(
        fixture, 10.0, "2026-08-28 15:59-04:00", "LONG",
        SwingReplayRule(stop_price=9.0, target_price=12.0, max_hold_sessions=1),
        split_end_date="2026-08-31", available_end_date="2026-08-31",
    )
    assert result.exit_reason == "STOP_SAME_BAR"
    assert result.exit_price == 9.0


def test_favourable_gap_through_target_uses_conservative_target_fill():
    fixture = bars([
        ("2026-08-28 15:59", 10.0, 10.0, 10.0, 10.0),
        ("2026-08-31 09:30", 13.0, 13.2, 12.8, 13.0),
        ("2026-08-31 15:59", 13.0, 13.1, 12.9, 13.0),
    ])
    result = simulate_multisession_trade(
        fixture, 10.0, "2026-08-28 15:59-04:00", "LONG",
        SwingReplayRule(stop_price=9.0, target_price=12.0, max_hold_sessions=1),
        split_end_date="2026-08-31", available_end_date="2026-08-31",
    )
    assert result.exit_reason == "TARGET"
    assert result.exit_price == 12.0


def signal():
    return {
        "strategy_id": "DAN_IRISH",
        "variant_id": "DAN_OVERNIGHT_NEXT_OPEN",
        "setup_id": "OVERNIGHT_NEXT_OPEN",
        "symbol": "AAA",
        "date": "2026-08-28",
        "split": "validation",
        "direction": "LONG",
        "entry_timestamp": "2026-08-28 15:59-04:00",
        "entry_price_slipped": 10.0,
        "stop_reference": 9.0,
    }


def test_hold_crossing_split_boundary_is_marked_censored():
    row = replay_swing_signal_grid(
        multi_day_bars(), signal(),
        rules=[SwingReplayRule(stop_pct=.10, target_pct=.50, max_hold_sessions=3)],
        split_end_date="2026-09-01", available_end_date="2026-09-03",
    ).iloc[0]
    assert bool(row["boundary_censored"]) is True
    assert bool(row["selection_eligible_replay"]) is False
    assert pd.isna(row["return_pct"])


def test_missing_future_sessions_is_right_censored():
    row = replay_swing_signal_grid(
        multi_day_bars().iloc[:5], signal(),
        rules=[SwingReplayRule(stop_pct=.10, target_pct=.50, max_hold_sessions=3)],
        split_end_date="2026-09-30", available_end_date="2026-09-01",
    ).iloc[0]
    assert bool(row["right_censored"]) is True
    assert bool(row["selection_eligible_replay"]) is False
    assert pd.isna(row["return_pct"])


def test_complete_hold_records_peak_timing_and_terminal_close():
    result = simulate_multisession_trade(
        multi_day_bars(), 10.0, "2026-08-28 15:59-04:00", "LONG",
        SwingReplayRule(stop_pct=.20, target_pct=.50, max_hold_sessions=2),
        split_end_date="2026-09-03", available_end_date="2026-09-03",
    )
    assert result.exit_reason == "TIME"
    assert result.exit_timestamp.date().isoformat() == "2026-09-01"
    assert result.exit_price == 11.1
    assert result.trading_days_to_peak in {1, 2}
    assert result.calendar_days_to_peak >= result.trading_days_to_peak


def test_swing_grid_prepares_shared_bars_once(monkeypatch):
    calls = 0
    original = multisession_replay._prepare_bars

    def counted(frame):
        nonlocal calls
        calls += 1
        return original(frame)

    monkeypatch.setattr(multisession_replay, "_prepare_bars", counted)
    out = replay_swing_signal_grid(
        multi_day_bars(),
        signal(),
        rules=[
            SwingReplayRule(stop_pct=.10, target_pct=.20, max_hold_sessions=1),
            SwingReplayRule(stop_pct=.10, target_pct=.30, max_hold_sessions=2),
            SwingReplayRule(stop_pct=.15, target_pct=.40, max_hold_sessions=3),
        ],
        split_end_date="2026-09-03",
        available_end_date="2026-09-03",
    )
    assert len(out) == 3
    assert calls == 1
