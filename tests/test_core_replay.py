import pandas as pd

from scanner.core.replay import ReplayRule, apply_entry_slippage, raw_return_pct, simulate_trade


def bars_at(rows):
    return pd.DataFrame([
        {
            "timestamp": pd.Timestamp(ts, tz="America/New_York").tz_convert("UTC"),
            "open": o, "high": h, "low": l, "close": c,
        }
        for ts, o, h, l, c in rows
    ])


def test_short_same_bar_stop_and_target_assumes_stop_first():
    bars = bars_at([("2026-08-28 10:00", 10.0, 10.6, 8.8, 9.2)])
    result = simulate_trade(
        bars, 10.0, "2026-08-28 10:00:00-04:00", "SHORT",
        ReplayRule(stop_pct=0.05, target_pct=0.10, max_hold_minutes=30),
    )
    assert result.exit_reason == "STOP_SAME_BAR"
    assert round(result.return_pct, 6) == -0.05


def test_long_same_bar_stop_and_target_assumes_stop_first():
    bars = bars_at([("2026-08-28 10:00", 10.0, 11.2, 9.4, 10.5)])
    result = simulate_trade(
        bars, 10.0, "2026-08-28 10:00:00-04:00", "LONG",
        ReplayRule(stop_pct=0.05, target_pct=0.10, max_hold_minutes=30),
    )
    assert result.exit_reason == "STOP_SAME_BAR"
    assert round(result.return_pct, 6) == -0.05


def test_long_and_short_slippage_move_entry_against_trader():
    assert apply_entry_slippage(10.0, "LONG", 25) == 10.025
    assert apply_entry_slippage(10.0, "SHORT", 25) == 9.975


def test_short_return_is_symmetric_on_entry_not_exit():
    assert raw_return_pct(10.0, 9.0, "SHORT") == 0.10
    assert raw_return_pct(10.0, 10.5, "SHORT") == -0.05
    assert raw_return_pct(10.0, 11.0, "LONG") == 0.10


def test_structural_stop_and_r_target_are_derived_from_entry_known_levels():
    bars = bars_at([
        ("2026-08-28 10:00", 10.0, 10.5, 9.8, 10.4),
        ("2026-08-28 10:01", 10.4, 11.1, 10.3, 10.9),
    ])
    rule = ReplayRule(stop_price=9.5, target_r_multiple=2.0, max_hold_minutes=30)
    result = simulate_trade(bars, 10.0, "2026-08-28 10:00:00-04:00", "LONG", rule)
    assert result.exit_reason == "TARGET"
    assert result.exit_price == 11.0
    assert round(result.r_multiple, 6) == 2.0


def test_long_replay_records_mfe_and_mae_before_time_exit():
    result = simulate_trade(
        bars_at([
            ("2026-08-28 10:00", 10.0, 10.5, 9.8, 10.1),
            ("2026-08-28 10:01", 10.1, 10.8, 9.9, 10.2),
        ]),
        10.0, "2026-08-28 10:00:00-04:00", "LONG",
        ReplayRule(stop_pct=0.20, target_pct=0.20, max_hold_minutes=2),
    )
    assert result.exit_reason == "TIME"
    assert round(result.mfe_pct, 4) == 0.08
    assert round(result.mae_pct, 4) == -0.02


def test_short_replay_records_mfe_and_mae():
    result = simulate_trade(
        bars_at([
            ("2026-08-28 10:00", 10.0, 10.2, 9.5, 9.8),
            ("2026-08-28 10:01", 9.8, 10.1, 9.2, 9.4),
        ]),
        10.0, "2026-08-28 10:00:00-04:00", "SHORT",
        ReplayRule(stop_pct=0.20, target_pct=0.20, max_hold_minutes=2),
    )
    assert round(result.mfe_pct, 4) == 0.08
    assert round(result.mae_pct, 4) == -0.02


def test_eod_hold_uses_session_end_not_next_day():
    bars = bars_at([
        ("2026-08-28 15:59", 10.0, 10.1, 9.9, 10.0),
        ("2026-08-28 16:00", 10.0, 10.2, 9.9, 10.1),
        ("2026-08-29 09:30", 10.1, 15.0, 10.0, 14.0),
    ])
    result = simulate_trade(
        bars, 10.0, "2026-08-28 15:59:00-04:00", "LONG",
        ReplayRule(stop_pct=0.50, target_pct=0.50, max_hold_minutes=None, hold_to_eod=True),
        session_end="16:00",
    )
    assert result.exit_reason == "EOD"
    assert str(result.exit_timestamp.date()) == "2026-08-28"
