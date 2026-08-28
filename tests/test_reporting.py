import pandas as pd

from scanner.serclick.reporting import (
    apply_variant,
    build_shortlist,
    profit_factor,
    summarize_replays,
    summarize_replays_by_market_cap,
)


def _ignitions():
    return pd.DataFrame([
        {"symbol": "AAA", "population": "BOTH", "ignition_window": "10:30-15:00", "split": "validation"},
        {"symbol": "BBB", "population": "BOTH", "ignition_window": "16:00-20:00", "split": "test"},
        {"symbol": "CCC", "population": "BOTH", "ignition_window": "09:30-10:30", "split": "validation"},
        {"symbol": "DDD", "population": "LEO_OPEN", "ignition_window": "10:30-15:00", "split": "validation"},
    ])


def test_midday_both_variant_excludes_morning_and_open_only():
    out = apply_variant(_ignitions(), "LEO_BOTH_MIDDAY")
    assert out["symbol"].tolist() == ["AAA"]


def test_profit_factor_is_gross_profit_over_gross_loss():
    assert profit_factor(pd.Series([0.10, -0.05, 0.20, -0.10])) == 2.0


def test_replay_summary_reports_expectancy_win_rate_and_pf():
    df = pd.DataFrame([
        {"variant": "LEO_BOTH_MIDDAY", "split": "validation", "rule_id": "S05_T10_H60", "return_pct": 0.10},
        {"variant": "LEO_BOTH_MIDDAY", "split": "validation", "rule_id": "S05_T10_H60", "return_pct": -0.05},
        {"variant": "LEO_BOTH_MIDDAY", "split": "validation", "rule_id": "S05_T10_H60", "return_pct": 0.10},
    ])
    out = summarize_replays(df)
    row = out.iloc[0]
    assert row["n"] == 3
    assert round(row["expectancy"], 6) == 0.05
    assert round(row["win_rate"], 6) == round(2 / 3, 6)
    assert row["profit_factor"] == 4.0


def test_market_cap_summary_keeps_microcap_and_small_cap_separate():
    df = pd.DataFrame([
        {"variant": "LEO_BOTH_MIDDAY", "split": "forward", "rule_id": "S05_T10_H60", "market_cap_bucket": "MICROCAP", "return_pct": 0.10},
        {"variant": "LEO_BOTH_MIDDAY", "split": "forward", "rule_id": "S05_T10_H60", "market_cap_bucket": "MICROCAP", "return_pct": -0.05},
        {"variant": "LEO_BOTH_MIDDAY", "split": "forward", "rule_id": "S05_T10_H60", "market_cap_bucket": "SMALL_CAP", "return_pct": 0.02},
    ])
    out = summarize_replays_by_market_cap(df)
    micro = out[out["market_cap_bucket"].eq("MICROCAP")].iloc[0]
    small = out[out["market_cap_bucket"].eq("SMALL_CAP")].iloc[0]
    assert micro["n"] == 2
    assert micro["profit_factor"] == 2.0
    assert small["n"] == 1


def test_shortlist_prioritizes_both_tradable_ignition_over_watch_names():
    candidates = pd.DataFrame([
        {"symbol": "AAA", "date": "2026-08-27", "population": "BOTH", "pm_extension": 1.4, "hod_1000_extension": 1.5},
        {"symbol": "BBB", "date": "2026-08-27", "population": "BOTH", "pm_extension": 1.3, "hod_1000_extension": 1.4},
        {"symbol": "CCC", "date": "2026-08-27", "population": "LEO_OPEN", "pm_extension": 1.1, "hod_1000_extension": 1.3},
    ])
    transitions = pd.DataFrame([
        {"symbol": "AAA", "date": "2026-08-27", "state": "IGNITION", "timestamp": "2026-08-27 11:00:00-04:00"},
        {"symbol": "BBB", "date": "2026-08-27", "state": "ARMED", "timestamp": "2026-08-27 12:00:00-04:00"},
        {"symbol": "CCC", "date": "2026-08-27", "state": "IGNITION", "timestamp": "2026-08-27 13:00:00-04:00"},
    ])
    ignitions = pd.DataFrame([
        {"symbol": "AAA", "date": "2026-08-27", "population": "BOTH", "ignition_window": "10:30-15:00", "entry_price_slipped": 4.25},
        {"symbol": "CCC", "date": "2026-08-27", "population": "LEO_OPEN", "ignition_window": "10:30-15:00", "entry_price_slipped": 3.00},
    ])
    out = build_shortlist(candidates, transitions, ignitions)
    assert out.iloc[0]["symbol"] == "AAA"
    assert out.iloc[0]["action"] == "TRADABLE_RESEARCH_SIGNAL"
    assert out[out["symbol"].eq("BBB")].iloc[0]["action"] == "WATCH"