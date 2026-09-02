import numpy as np
import pandas as pd

from scanner.strategies.dan_irish.stability import summarize_dan_threshold_stability


def _row(**overrides):
    row = {
        "strategy_id": "DAN_IRISH",
        "variant_id": "DAN_INTRADAY_SECONDARY",
        "setup_id": "C20_BASE_HIGH_V1P5",
        "rule_id": "C20_BASE_HIGH_V1P5__S08_T20_H60",
        "split": "validation",
        "slippage_bps": 25.0,
        "min_impulse_pct": 0.15,
        "min_dollar_turnover": 1_000_000.0,
        "min_retained_gain": 0.40,
        "max_pullback_depth": 0.10,
        "n": 30,
        "expectancy": 0.08,
        "profit_factor": 1.8,
    }
    row.update(overrides)
    return row


def test_threshold_stability_counts_adjacent_parameter_plateau():
    frame = pd.DataFrame([
        _row(),
        _row(min_impulse_pct=0.20, expectancy=0.07, profit_factor=1.6),
        _row(min_dollar_turnover=3_000_000.0, expectancy=0.06, profit_factor=1.5),
        _row(min_retained_gain=0.50, expectancy=0.05, profit_factor=1.4),
        _row(max_pullback_depth=0.20, expectancy=-0.01, profit_factor=0.9),
    ])

    out = summarize_dan_threshold_stability(frame, min_n=20)
    center = out[
        out["min_impulse_pct"].eq(0.15)
        & out["min_dollar_turnover"].eq(1_000_000.0)
        & out["min_retained_gain"].eq(0.40)
        & out["max_pullback_depth"].eq(0.10)
    ].iloc[0]

    assert center["possible_neighbor_n"] == 4
    assert center["observed_neighbor_n"] == 4
    assert center["stable_neighbor_n"] == 3
    assert np.isclose(center["plateau_stability"], 0.75)
    assert bool(center["self_qualifies"])


def test_missing_neighbor_is_not_treated_as_stable():
    frame = pd.DataFrame([
        _row(),
        _row(min_impulse_pct=0.20),
        _row(min_dollar_turnover=3_000_000.0),
    ])

    out = summarize_dan_threshold_stability(frame, min_n=20)
    center = out[
        out["min_impulse_pct"].eq(0.15)
        & out["min_dollar_turnover"].eq(1_000_000.0)
        & out["min_retained_gain"].eq(0.40)
        & out["max_pullback_depth"].eq(0.10)
    ].iloc[0]

    assert center["possible_neighbor_n"] == 4
    assert center["observed_neighbor_n"] == 2
    assert center["stable_neighbor_n"] == 2
    assert np.isclose(center["plateau_stability"], 0.50)
