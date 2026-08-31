import numpy as np
import pandas as pd

from scanner.core.reporting import (
    summarize_censoring,
    summarize_strategy_replays,
    summarize_swing_holds,
)
from scanner.strategies.dan_irish.rules import default_dan_swing_rules


def _replays():
    base = {
        "strategy_id": "DAN_IRISH",
        "variant_id": "DAN_DAY2_CONTINUATION",
        "direction": "LONG",
        "split": "validation",
        "rule_id": "STRUCT_R2_HS2",
        "setup_id": "ret65_base1_break_base_high",
        "max_hold_sessions": 2,
        "stop_mode": "STRUCTURAL",
        "slippage_bps": 25.0,
    }
    return pd.DataFrame([
        {**base, "date": "2026-08-03", "return_pct": 0.20, "r_multiple": 2.0, "mfe_pct": 0.30, "mae_pct": -0.05,
         "boundary_censored": False, "right_censored": False, "selection_eligible_replay": True},
        {**base, "date": "2026-08-04", "return_pct": -0.10, "r_multiple": -1.0, "mfe_pct": 0.04, "mae_pct": -0.12,
         "boundary_censored": False, "right_censored": False, "selection_eligible_replay": True},
        # Defensive case: a censored row must be excluded even if it accidentally carries a return.
        {**base, "date": "2026-08-05", "return_pct": 9.99, "r_multiple": 99.0, "mfe_pct": 10.0, "mae_pct": 0.0,
         "boundary_censored": True, "right_censored": False, "selection_eligible_replay": False},
        # Same replay rule but different setup identity must never be pooled.
        {**base, "setup_id": "ret80_base1_break_base_high", "date": "2026-08-06", "return_pct": 0.05,
         "r_multiple": 0.5, "mfe_pct": 0.08, "mae_pct": -0.02,
         "boundary_censored": False, "right_censored": False, "selection_eligible_replay": True},
    ])


def test_dan_swing_rule_grid_contains_all_hold_horizons_and_structural_rules():
    rules = default_dan_swing_rules({"stop_reference": 8.5})
    assert {r.max_hold_sessions for r in rules} == {1, 2, 3, 4, 5, 7, 10}
    assert any(r.stop_price == 8.5 and r.target_r_multiple == 2.0 for r in rules)
    assert any(r.stop_pct == 0.08 for r in rules)
    assert len({r.rule_id for r in rules}) == len(rules)


def test_strategy_summary_excludes_censored_rows_and_keeps_setup_identity_separate():
    summary = summarize_strategy_replays(_replays())
    assert "setup_id" in summary.columns
    assert len(summary) == 2
    first = summary[summary["setup_id"].eq("ret65_base1_break_base_high")].iloc[0]
    assert first["n"] == 2
    assert np.isclose(first["expectancy"], 0.05)
    assert np.isclose(first["profit_factor"], 2.0)


def test_censoring_summary_reports_boundary_and_right_edge_counts():
    x = _replays()
    extra = x.iloc[[0]].copy()
    extra["date"] = "2026-08-07"
    extra["return_pct"] = np.nan
    extra["boundary_censored"] = False
    extra["right_censored"] = True
    extra["selection_eligible_replay"] = False
    out = summarize_censoring(pd.concat([x, extra], ignore_index=True))
    row = out[out["setup_id"].eq("ret65_base1_break_base_high")].iloc[0]
    assert row["replays_total"] == 4
    assert row["eligible_replays"] == 2
    assert row["boundary_censored_n"] == 1
    assert row["right_censored_n"] == 1


def test_swing_hold_summary_keeps_horizon_and_peak_timing():
    x = _replays().copy()
    x["trading_days_to_peak"] = [1.0, 0.0, 2.0, 1.0]
    x["calendar_days_to_peak"] = [1.0, 0.0, 3.0, 1.0]
    out = summarize_swing_holds(x)
    row = out[out["setup_id"].eq("ret65_base1_break_base_high")].iloc[0]
    assert row["max_hold_sessions"] == 2
    assert row["n"] == 2
    assert np.isclose(row["mean_trading_days_to_peak"], 0.5)
