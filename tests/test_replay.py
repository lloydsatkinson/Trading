import pandas as pd

from scanner.serclick.replay import ReplayRule, replay_signal_grid, simulate_long_trade


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


def test_replay_grid_preserves_prospective_market_cap_tags():
    bars = _bars([("2026-08-28 11:01", 10.0, 10.2, 9.9, 10.1)])
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
