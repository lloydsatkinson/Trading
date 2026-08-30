import pandas as pd

from scripts.run_strategy_research import (
    build_slippage_summary,
    reprice_signal_for_slippage,
    session_end_for_strategy,
    summarize_peak_timing,
)


def test_reprice_signal_applies_adverse_slippage_from_raw_entry():
    long = reprice_signal_for_slippage({"entry_price_raw": 10.0, "direction": "LONG"}, 25)
    short = reprice_signal_for_slippage({"entry_price_raw": 10.0, "direction": "SHORT"}, 25)
    assert long["entry_price_slipped"] == 10.025
    assert short["entry_price_slipped"] == 9.975
    assert long["slippage_bps"] == 25


def test_session_boundary_depends_on_strategy_family():
    assert session_end_for_strategy("ORB") == "16:00"
    assert session_end_for_strategy("VWAP") == "16:00"
    assert session_end_for_strategy("SERCLICK_LEO") == "20:00"


def test_slippage_summary_reports_break_points_per_rule():
    summary = pd.DataFrame([
        {"strategy_id":"ORB","variant_id":"V","direction":"LONG","rule_id":"R","split":"validation","slippage_bps":10,"profit_factor":1.8},
        {"strategy_id":"ORB","variant_id":"V","direction":"LONG","rule_id":"R","split":"validation","slippage_bps":25,"profit_factor":1.4},
        {"strategy_id":"ORB","variant_id":"V","direction":"LONG","rule_id":"R","split":"validation","slippage_bps":50,"profit_factor":1.1},
        {"strategy_id":"ORB","variant_id":"V","direction":"LONG","rule_id":"R","split":"validation","slippage_bps":75,"profit_factor":0.9},
    ])
    out = build_slippage_summary(summary).iloc[0]
    assert out["pf_below_1_2_bps"] == 50
    assert out["pf_below_1_0_bps"] == 75


def test_peak_summary_deduplicates_rule_grid_at_baseline_slippage():
    rows = []
    for rule in ("A", "B"):
        rows.append({
            "strategy_id":"VWAP","variant_id":"V","direction":"LONG","symbol":"AAA","date":"2026-08-28",
            "split":"validation","slippage_bps":25,"rule_id":rule,"peak_return_pct":0.20,"minutes_to_peak":37,
            "market_cap_bucket":"MICROCAP",
        })
    out = summarize_peak_timing(pd.DataFrame(rows))
    assert out.iloc[0]["n_signals"] == 1
    assert out.iloc[0]["median_minutes_to_peak"] == 37
