import pandas as pd

from scanner.serclick import reporting
from scanner.serclick.reporting import (
    apply_variant,
    build_latest_results,
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
        {"variant": "LEO_BOTH_MIDDAY", "split": "validation", "rule_id": "S05_T10_H60", "stop_pct": 0.05, "target_pct": 0.10, "max_hold_minutes": 60, "return_pct": 0.10},
        {"variant": "LEO_BOTH_MIDDAY", "split": "validation", "rule_id": "S05_T10_H60", "stop_pct": 0.05, "target_pct": 0.10, "max_hold_minutes": 60, "return_pct": -0.05},
        {"variant": "LEO_BOTH_MIDDAY", "split": "validation", "rule_id": "S05_T10_H60", "stop_pct": 0.05, "target_pct": 0.10, "max_hold_minutes": 60, "return_pct": 0.10},
    ])
    out = summarize_replays(df)
    row = out.iloc[0]
    assert row["n"] == 3
    assert round(row["expectancy"], 6) == 0.05
    assert round(row["win_rate"], 6) == round(2 / 3, 6)
    assert row["profit_factor"] == 4.0


def test_replay_summary_reports_1000_gbp_position_and_planned_stop_loss():
    df = pd.DataFrame([
        {"variant": "LEO_BOTH_MIDDAY", "split": "validation", "rule_id": "S50_T30_H60", "stop_pct": 0.50, "target_pct": 0.30, "max_hold_minutes": 60, "return_pct": 0.30},
        {"variant": "LEO_BOTH_MIDDAY", "split": "validation", "rule_id": "S50_T30_H60", "stop_pct": 0.50, "target_pct": 0.30, "max_hold_minutes": 60, "return_pct": -0.50},
    ])
    row = summarize_replays(df).iloc[0]
    assert row["stop_pct"] == 0.50
    assert row["planned_stop_gbp_1000"] == 500.0
    assert row["avg_pnl_gbp_1000"] == -100.0
    assert row["worst_pnl_gbp_1000"] == -500.0


def test_market_cap_summary_keeps_microcap_and_small_cap_separate():
    df = pd.DataFrame([
        {"variant": "LEO_BOTH_MIDDAY", "split": "forward", "rule_id": "S05_T10_H60", "stop_pct": 0.05, "target_pct": 0.10, "max_hold_minutes": 60, "market_cap_bucket": "MICROCAP", "return_pct": 0.10},
        {"variant": "LEO_BOTH_MIDDAY", "split": "forward", "rule_id": "S05_T10_H60", "stop_pct": 0.05, "target_pct": 0.10, "max_hold_minutes": 60, "market_cap_bucket": "MICROCAP", "return_pct": -0.05},
        {"variant": "LEO_BOTH_MIDDAY", "split": "forward", "rule_id": "S05_T10_H60", "stop_pct": 0.05, "target_pct": 0.10, "max_hold_minutes": 60, "market_cap_bucket": "SMALL_CAP", "return_pct": 0.02},
    ])
    out = summarize_replays_by_market_cap(df)
    micro = out[out["market_cap_bucket"].eq("MICROCAP")].iloc[0]
    small = out[out["market_cap_bucket"].eq("SMALL_CAP")].iloc[0]
    assert micro["n"] == 2
    assert micro["profit_factor"] == 2.0
    assert micro["avg_pnl_gbp_1000"] == 25.0
    assert small["n"] == 1


def test_best_rules_never_use_forward_split_for_selection():
    replay_summary = pd.DataFrame([
        {"variant": "LEO_BOTH_MIDDAY", "split": "validation", "rule_id": "S20_T30_H60", "stop_pct": 0.20, "target_pct": 0.30, "max_hold_minutes": 60, "n": 10, "expectancy": 0.04, "median_return": 0.03, "win_rate": 0.60, "profit_factor": 1.8, "avg_pnl_gbp_1000": 40.0, "worst_pnl_gbp_1000": -200.0, "planned_stop_gbp_1000": 200.0},
        {"variant": "LEO_BOTH_MIDDAY", "split": "forward", "rule_id": "S50_T30_H60", "stop_pct": 0.50, "target_pct": 0.30, "max_hold_minutes": 60, "n": 10, "expectancy": 0.30, "median_return": 0.30, "win_rate": 1.0, "profit_factor": 99.0, "avg_pnl_gbp_1000": 300.0, "worst_pnl_gbp_1000": 300.0, "planned_stop_gbp_1000": 500.0},
    ])
    ignitions = pd.DataFrame([{"symbol": "AAA", "date": "2026-08-28", "population": "BOTH", "ignition_window": "10:30-15:00"}])
    result = build_latest_results({"end_date": "2026-08-28"}, ignitions, replay_summary)
    selected = result["best_development_validation_rules"]
    assert [row["rule_id"] for row in selected] == ["S20_T30_H60"]


def test_select_best_hold_times_uses_only_development_validation_and_maximizes_average_pnl():
    rows = [
        {"variant": "LEO_BOTH_MIDDAY", "split": "development", "rule_id": "S20_T30_H30", "stop_pct": 0.20, "target_pct": 0.30, "max_hold_minutes": 30, "return_pct": 0.10},
        {"variant": "LEO_BOTH_MIDDAY", "split": "validation", "rule_id": "S20_T30_H30", "stop_pct": 0.20, "target_pct": 0.30, "max_hold_minutes": 30, "return_pct": -0.05},
        {"variant": "LEO_BOTH_MIDDAY", "split": "development", "rule_id": "S20_T30_H60", "stop_pct": 0.20, "target_pct": 0.30, "max_hold_minutes": 60, "return_pct": 0.20},
        {"variant": "LEO_BOTH_MIDDAY", "split": "validation", "rule_id": "S20_T30_H60", "stop_pct": 0.20, "target_pct": 0.30, "max_hold_minutes": 60, "return_pct": -0.05},
        {"variant": "LEO_BOTH_MIDDAY", "split": "forward", "rule_id": "S20_T30_H30", "stop_pct": 0.20, "target_pct": 0.30, "max_hold_minutes": 30, "return_pct": 1.00},
    ]
    out = reporting.select_best_hold_times(pd.DataFrame(rows), min_n=2)
    assert len(out) == 1
    assert out.iloc[0]["max_hold_minutes"] == 60
    assert out.iloc[0]["selection_splits"] == "development+validation"
    assert round(float(out.iloc[0]["avg_pnl_gbp_1000"]), 6) == 75.0


def test_peak_timing_summary_deduplicates_rules_per_signal():
    rows = [
        {"symbol": "AAA", "date": "2026-08-28", "variant": "LEO_BOTH_MIDDAY", "split": "forward", "market_cap_bucket": "MICROCAP", "rule_id": "S20_T30_H30", "peak_return_pct": 0.20, "minutes_to_peak": 5},
        {"symbol": "AAA", "date": "2026-08-28", "variant": "LEO_BOTH_MIDDAY", "split": "forward", "market_cap_bucket": "MICROCAP", "rule_id": "S20_T30_H60", "peak_return_pct": 0.20, "minutes_to_peak": 5},
        {"symbol": "BBB", "date": "2026-08-29", "variant": "LEO_BOTH_MIDDAY", "split": "forward", "market_cap_bucket": "MICROCAP", "rule_id": "S20_T30_H30", "peak_return_pct": 0.10, "minutes_to_peak": 15},
    ]
    out = reporting.summarize_peak_timing(pd.DataFrame(rows))
    row = out.iloc[0]
    assert row["market_cap_bucket"] == "MICROCAP"
    assert row["n_signals"] == 2
    assert row["median_minutes_to_peak"] == 10.0
    assert round(float(row["median_peak_return_pct"]), 6) == 0.15


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
