import pandas as pd

from scanner.core.multisession_replay import SwingReplayRule, simulate_multisession_trade
from scanner.strategies.dan_irish.rules import default_dan_swing_rules


def _bars(rows):
    return pd.DataFrame([
        {
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


def test_default_swing_grid_includes_all_available_structural_stop_families():
    signal = {
        "entry_price_slipped": 10.0,
        "stop_reference": 8.9,
        "prior_day_low": 9.1,
        "day0_support": 8.7,
        "pre_entry_atr": 0.5,
        "anchored_vwap_at_entry": 9.4,
    }
    rules = default_dan_swing_rules(signal)
    modes = {str(rule.stop_mode).upper() for rule in rules}
    assert {
        "PCT",
        "STRUCTURAL_BASE",
        "PRIOR_DAY_LOW",
        "DAY0_SUPPORT",
        "ATR",
        "ANCHORED_VWAP",
    }.issubset(modes)
    trails = {str(rule.trailing_exit or "NONE").upper() for rule in rules}
    assert {
        "NONE",
        "PRIOR_DAY_LOW_BREAK",
        "BASE_FAILURE",
        "ANCHORED_VWAP_LOSS",
        "TRAILING_HIGHER_LOW",
    }.issubset(trails)


def test_prior_day_low_trail_uses_only_completed_previous_session_low():
    bars = _bars([
        ("2026-08-31 09:30", 10.0, 10.2, 9.8, 10.1, 100, 10.05),
        ("2026-08-31 15:59", 10.2, 10.4, 9.7, 10.3, 100, 10.15),
        ("2026-09-01 09:30", 10.25, 10.3, 9.9, 10.0, 100, 10.1),
        ("2026-09-01 10:00", 10.0, 10.1, 9.65, 9.68, 100, 9.9),
        ("2026-09-01 15:59", 9.8, 9.9, 8.0, 8.5, 100, 8.8),
        ("2026-09-02 09:30", 8.6, 8.8, 8.4, 8.7, 100, 8.6),
        ("2026-09-02 15:59", 8.8, 9.0, 8.5, 8.9, 100, 8.8),
    ])
    result = simulate_multisession_trade(
        bars,
        entry_price=10.0,
        entry_timestamp=pd.Timestamp("2026-08-31 09:30", tz="America/New_York"),
        direction="LONG",
        rule=SwingReplayRule(
            stop_mode="STRUCTURAL_BASE",
            stop_price=9.0,
            trailing_exit="PRIOR_DAY_LOW_BREAK",
            max_hold_sessions=2,
        ),
        split_end_date="2026-09-02",
        available_end_date="2026-09-02",
    )
    # Aug-31 completes with a 9.70 low. Sep-1 must therefore use 9.70;
    # the later Sep-1 crash cannot retroactively define that session's stop.
    assert result.exit_reason == "PRIOR_DAY_LOW_BREAK"
    assert pd.Timestamp(result.exit_timestamp).tz_convert("America/New_York") == pd.Timestamp(
        "2026-09-01 10:00", tz="America/New_York"
    )
    assert result.exit_price == 9.7


def test_anchored_vwap_loss_uses_only_information_through_current_bar():
    bars = _bars([
        ("2026-08-31 09:30", 10.0, 10.1, 9.95, 10.0, 100, 10.0),
        ("2026-08-31 09:31", 10.0, 10.02, 9.75, 9.80, 100, 9.90),
        ("2026-08-31 15:59", 9.8, 9.9, 9.7, 9.8, 100, 9.8),
        ("2026-09-01 09:30", 9.8, 9.9, 9.7, 9.8, 100, 9.8),
        ("2026-09-01 15:59", 9.9, 10.0, 9.8, 9.9, 100, 9.9),
    ])
    result = simulate_multisession_trade(
        bars,
        entry_price=10.0,
        entry_timestamp=pd.Timestamp("2026-08-31 09:30", tz="America/New_York"),
        direction="LONG",
        rule=SwingReplayRule(
            stop_mode="STRUCTURAL_BASE",
            stop_price=9.0,
            trailing_exit="ANCHORED_VWAP_LOSS",
            max_hold_sessions=1,
        ),
        split_end_date="2026-09-01",
        available_end_date="2026-09-01",
    )
    assert result.exit_reason == "ANCHORED_VWAP_LOSS"
    assert pd.Timestamp(result.exit_timestamp).tz_convert("America/New_York") == pd.Timestamp(
        "2026-08-31 09:31", tz="America/New_York"
    )


def test_trailing_higher_low_never_moves_stop_down():
    bars = _bars([
        ("2026-08-31 09:30", 10.0, 10.3, 9.8, 10.2, 100, 10.1),
        ("2026-08-31 15:59", 10.3, 10.5, 9.9, 10.4, 100, 10.25),
        ("2026-09-01 09:30", 10.4, 10.6, 10.1, 10.5, 100, 10.45),
        ("2026-09-01 15:59", 10.5, 10.7, 10.0, 10.6, 100, 10.5),
        ("2026-09-02 09:30", 10.05, 10.1, 9.85, 9.9, 100, 9.95),
        ("2026-09-02 15:59", 9.9, 10.0, 9.7, 9.8, 100, 9.85),
    ])
    result = simulate_multisession_trade(
        bars,
        entry_price=10.0,
        entry_timestamp=pd.Timestamp("2026-08-31 09:30", tz="America/New_York"),
        direction="LONG",
        rule=SwingReplayRule(
            stop_mode="STRUCTURAL_BASE",
            stop_price=9.0,
            trailing_exit="TRAILING_HIGHER_LOW",
            max_hold_sessions=2,
        ),
        split_end_date="2026-09-02",
        available_end_date="2026-09-02",
    )
    assert result.exit_reason == "TRAILING_HIGHER_LOW"
    # Stop raises first to 9.80, then to 10.00 after Sep-1 completes.
    assert result.exit_price == 10.0
