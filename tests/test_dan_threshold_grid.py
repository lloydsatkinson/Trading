import numpy as np
import pandas as pd

from scanner.strategies.dan_irish.research import (
    persist_dan_rule_identity,
    summarize_dan_threshold_grid,
)


def _replays():
    base = {
        "strategy_id": "DAN_IRISH",
        "variant_id": "DAN_INTRADAY_SECONDARY",
        "setup_id": "C10_BASE_HIGH_V1P0",
        "rule_id": "S05_T10_H60",
        "split": "validation",
        "slippage_bps": 25.0,
        "price_bucket": "2_5",
        "market_cap_bucket": "MICROCAP",
        "selection_eligible_replay": True,
    }
    return pd.DataFrame([
        {
            **base,
            "impulse_pct": 0.82,
            "pm_dollar_turnover": 12_000_000.0,
            "retained_gain_ratio": 0.86,
            "pullback_depth": 0.08,
            "return_pct": 0.20,
            "r_multiple": 2.0,
        },
        {
            **base,
            "impulse_pct": 0.32,
            "pm_dollar_turnover": 4_000_000.0,
            "retained_gain_ratio": 0.68,
            "pullback_depth": 0.28,
            "return_pct": -0.10,
            "r_multiple": -1.0,
        },
        # Censored rows must never enter threshold expectancy/PF.
        {
            **base,
            "impulse_pct": 1.50,
            "pm_dollar_turnover": 30_000_000.0,
            "retained_gain_ratio": 0.95,
            "pullback_depth": 0.02,
            "return_pct": 9.99,
            "r_multiple": 99.0,
            "selection_eligible_replay": False,
        },
    ])


def test_persisted_dan_rule_identity_includes_setup_and_exit_rule():
    out = persist_dan_rule_identity(_replays().iloc[:1].copy())
    row = out.iloc[0]
    assert row["exit_rule_id"] == "S05_T10_H60"
    assert row["rule_id"] == "C10_BASE_HIGH_V1P0__S05_T10_H60"


def test_threshold_grid_is_auditable_and_excludes_censored_rows():
    out = summarize_dan_threshold_grid(_replays())
    required = {
        "strategy_id", "variant_id", "setup_id", "rule_id", "split", "slippage_bps",
        "min_impulse_pct", "min_dollar_turnover", "min_retained_gain", "max_pullback_depth",
        "n", "win_rate", "expectancy", "profit_factor", "mean_r", "max_drawdown",
    }
    assert required.issubset(out.columns)

    strict = out[
        out["min_impulse_pct"].eq(0.75)
        & out["min_dollar_turnover"].eq(10_000_000.0)
        & out["min_retained_gain"].eq(0.80)
        & out["max_pullback_depth"].eq(0.10)
    ]
    assert len(strict) == 1
    row = strict.iloc[0]
    assert row["n"] == 1
    assert np.isclose(row["expectancy"], 0.20)
    assert np.isinf(row["profit_factor"])
    assert np.isclose(row["mean_r"], 2.0)


def test_threshold_grid_keeps_setup_identity_separate():
    x = _replays().iloc[:2].copy()
    second = x.iloc[[0]].copy()
    second["setup_id"] = "C30_BASE_HIGH_V1P0"
    second["return_pct"] = -0.20
    second["r_multiple"] = -2.0
    out = summarize_dan_threshold_grid(pd.concat([x, second], ignore_index=True))
    loose = out[
        out["min_impulse_pct"].eq(0.15)
        & out["min_dollar_turnover"].eq(1_000_000.0)
        & out["min_retained_gain"].eq(0.40)
        & out["max_pullback_depth"].eq(0.50)
    ]
    assert set(loose["setup_id"]) == {"C10_BASE_HIGH_V1P0", "C30_BASE_HIGH_V1P0"}
