import pandas as pd

from scanner.serclick.replay import (
    ReplayRule,
    analyze_same_session_peak,
    default_rule_grid,
    replay_signal_grid,
    simulate_long_trade,
)


def _bars(rows):
    return pd.DataFrame([{"timestamp_et": pd.Timestamp(ts, tz="America/New_York"), "open": o, "high": h, "low": l, "close": c} for ts, o, h, l, c in rows])


def test_same_bar_stop_and_target_uses_conservative_stop_first():
    bars = _bars([("2026-08-27 10:31", 10.0, 11.2, 9.4, 10.5)])
    result = simulate_long_trade(bars, entry_price=10.0, entry_timestamp=pd.Timestamp("2026-08-27 10:31", tz="America/New_York"), rule=ReplayRule(stop_pct=0.05, target_pct=0.10, max_hold_minutes=60))
    assert result.exit_reason == "STOP_SAME_BAR"
    assert result.return_pct == -0.05


def test_target_hit_before_stop_across_bars():
    bars = _bars([("2026-08-27 10:31", 10.0, 10.4, 9.8, 10.2), ("2026-08-27 10:32", 10.2, 11.1, 10.1, 11.0)])
    result = simulate_long_trade(bars, entry_price=10.0, entry_timestamp=pd.Timestamp("2026-08-27 10:31", tz="America/New_York"), rule=ReplayRule(stop_pct=0.05, target_pct=0.10, max_hold_minutes=60))
    assert result.exit_reason == "TARGET"
    assert result.return_pct == 0.10


def test_time_exit_uses_last_close_within_horizon():
    bars = _bars([("2026-08-27 10:31", 10.0, 10.2, 9.9, 10.1), ("2026-08-27 10:32", 10.1, 10.3, 10.0, 10.2), ("2026-08-27 10:33", 10.2, 10.4, 10.1, 10.3), ("2026-08-27 10:34", 10.3, 10.5, 10.2, 10.4)])
    result = simulate_long_trade(bars, entry_price=10.0, entry_timestamp=pd.Timestamp("2026-08-27 10:31", tz="America/New_York"), rule=ReplayRule(stop_pct=0.20, target_pct=0.20, max_hold_minutes=2))
    assert result.exit_reason == "TIME"
    assert round(result.return_pct, 6) == 0.03


def test_replay_never_holds_past_2000_et_same_session():
    bars = _bars([
        ("2026-08-27 19:58", 10.0, 10.2, 9.9, 10.0),
        ("2026-08-27 19:59", 10.0, 12.2, 9.9, 12.0),
        ("2026-08-27 20:00", 12.0, 15.0, 11.8, 14.0),
        ("2026-08-27 20:01", 14.0, 20.0, 13.9, 19.0),
    ])
    result = simulate_long_trade(
        bars,
        entry_price=10.0,
        entry_timestamp=pd.Timestamp("2026-08-27 19:58", tz="America/New_York"),
        rule=ReplayRule(stop_pct=0.50, target_pct=0.50, max_hold_minutes=10),
    )
    assert result.exit_reason == "TIME"
    assert result.exit_timestamp == pd.Timestamp("2026-08-27 19:59", tz="America/New_York")
    assert result.return_pct == 0.20


def test_same_session_peak_records_exact_elapsed_minutes_and_ignores_post_session_bars():
    bars = _bars([
        ("2026-08-27 10:31", 10.0, 10.2, 9.9, 10.1),
        ("2026-08-27 10:36", 10.1, 12.0, 10.0, 11.8),
        ("2026-08-27 19:59", 11.8, 11.9, 11.0, 11.2),
        ("2026-08-27 20:01", 11.2, 15.0, 11.0, 14.5),
    ])
    peak = analyze_same_session_peak(
        bars,
        entry_price=10.0,
        entry_timestamp=pd.Timestamp("2026-08-27 10:31", tz="America/New_York"),
    )
    assert peak.peak_timestamp == pd.Timestamp("2026-08-27 10:36", tz="America/New_York")
    assert peak.peak_return_pct == 0.20
    assert peak.minutes_to_peak == 5


def test_replay_grid_preserves_prospective_market_cap_tags_and_peak_metrics():
    bars = _bars([("2026-08-28 11:01", 10.0, 10.2, 9.9, 10.1), ("2026-08-28 11:03", 10.1, 11.0, 10.0, 10.8)])
    signal = {
        "symbol": "AAA",
        "date": "2026-08-28",
        "split": "forward",
        "population": "BOTH",
        "ignition_window": "10:30-15:00",
        "entry_price_slipped": 10.0,
        "entry_timestamp": pd.Timestamp("2026-08-28 11:01", tz="America/New_York"),
        "market_cap": 75_000_000.0,
        "market_cap_bucket": "MICROCAP",
        "is_microcap": True,
        "market_cap_source": "NASDAQ_SCREENER_CURRENT",
        "market_cap_asof": "2026-08-28T21:30:00-04:00",
    }
    out = replay_signal_grid(bars, signal, rules=[ReplayRule(stop_pct=0.20, target_pct=0.20, max_hold_minutes=1)])
    assert out.iloc[0]["market_cap_bucket"] == "MICROCAP"
    assert out.iloc[0]["market_cap"] == 75_000_000.0
    assert out.iloc[0]["peak_return_pct"] == 0.10
    assert out.iloc[0]["minutes_to_peak"] == 2


def test_default_rule_grid_includes_variable_stops_and_expanded_hold_times():
    rules = default_rule_grid()
    stops = sorted({round(rule.stop_pct, 2) for rule in rules})
    holds = sorted({rule.max_hold_minutes for rule in rules})
    assert stops == [0.03, 0.05, 0.07, 0.10, 0.15, 0.20, 0.30, 0.40, 0.50]
    assert holds == [5, 10, 15, 30, 45, 60, 90, 120, 180, 240]
    assert len(rules) == 450
