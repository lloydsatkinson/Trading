import pandas as pd

from trading_lab.prerunner_data import (
    build_case_control_manifest,
    identify_cases,
    select_controls,
)


def _universe():
    return pd.DataFrame([
        {"ticker": "RUN", "previous_close": 2.0, "prior20_median_volume": 500_000, "high": 2.6, "low": 1.9, "close": 2.5},
        {"ticker": "DROP", "previous_close": 3.0, "prior20_median_volume": 600_000, "high": 3.1, "low": 2.2, "close": 2.4},
        {"ticker": "C1", "previous_close": 2.1, "prior20_median_volume": 520_000, "high": 2.15, "low": 2.0, "close": 2.1},
        {"ticker": "C2", "previous_close": 3.1, "prior20_median_volume": 620_000, "high": 3.2, "low": 3.0, "close": 3.1},
        {"ticker": "C3", "previous_close": 8.0, "prior20_median_volume": 2_000_000, "high": 8.1, "low": 7.9, "close": 8.0},
    ])


def test_identify_cases_marks_up_and_down_extremes():
    out = identify_cases(_universe(), long_threshold=0.20, short_threshold=0.20)
    by = out.set_index("ticker")
    assert bool(by.loc["RUN", "case_long"])
    assert bool(by.loc["DROP", "case_short"])
    assert not bool(by.loc["C1", "case_long"])
    assert not bool(by.loc["C1", "case_short"])


def test_controls_depend_on_prior_information_not_same_day_outcomes():
    a = _universe()
    case_tickers = {"RUN", "DROP"}
    chosen_a = select_controls(a, case_tickers, controls_per_case=1, session_date="2026-08-10")

    b = a.copy()
    # Change same-day OHLC for non-cases without changing prior price/liquidity context.
    b.loc[b.ticker.str.startswith("C"), ["high", "low", "close"]] = [99.0, 0.8, 50.0]
    chosen_b = select_controls(b, case_tickers, controls_per_case=1, session_date="2026-08-10")
    assert chosen_a == chosen_b


def test_manifest_keeps_cases_and_deterministic_controls():
    out = build_case_control_manifest(
        _universe(),
        session_date="2026-08-10",
        controls_per_case=1,
        min_controls_per_day=1,
    )
    assert {"RUN", "DROP"}.issubset(set(out.ticker))
    assert (out.selection_role == "control").sum() >= 1
    assert out.ticker.is_unique


def test_quiet_day_still_samples_controls_for_base_rate_context():
    x = _universe().copy()
    x["high"] = x.previous_close * 1.02
    x["low"] = x.previous_close * 0.98
    out = build_case_control_manifest(
        x,
        session_date="2026-08-11",
        controls_per_case=1,
        min_controls_per_day=2,
    )
    assert len(out) == 2
    assert set(out.selection_role) == {"control"}
