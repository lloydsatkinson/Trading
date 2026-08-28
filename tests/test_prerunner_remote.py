import pandas as pd

from trading_lab.prerunner_remote import (
    daily_prior_context,
    select_signal_time_candidates,
)


def _daily_row(day, close, volume, high=None, low=None):
    return {
        "t": f"{day}T04:00:00Z",
        "c": close,
        "h": high if high is not None else close * 1.02,
        "l": low if low is not None else close * 0.98,
        "v": volume,
    }


def test_daily_prior_context_uses_only_prior_sessions():
    sessions = [pd.Timestamp(f"2026-08-0{d}").date() for d in range(3, 7)]
    daily_a = {
        "AAA": [
            _daily_row("2026-08-03", 2.0, 100_000),
            _daily_row("2026-08-04", 2.1, 200_000),
            _daily_row("2026-08-05", 2.2, 300_000),
            _daily_row("2026-08-06", 2.3, 999_999),
        ]
    }
    a = daily_prior_context(daily_a, sessions)
    d = sessions[-1]
    assert a[("AAA", d)]["previous_close"] == 2.2
    assert a[("AAA", d)]["prior20_median_volume"] == 200_000

    daily_b = {"AAA": [dict(r) for r in daily_a["AAA"]]}
    daily_b["AAA"][-1]["v"] = 50_000_000
    b = daily_prior_context(daily_b, sessions)
    assert b[("AAA", d)]["prior20_median_volume"] == 200_000


def _snapshots():
    return pd.DataFrame([
        {
            "session_date": "2026-08-10", "ticker": "HOT", "freeze_time": "09:31",
            "previous_close": 2.0, "prior20_median_volume": 400_000,
            "snapshot_price": 2.20, "pm_gap_pct": 0.08, "pm_dollar_volume": 500_000,
            "impulse_pct": 0.10, "open_rvol": 4.0, "open_cum_volume": 250_000,
            "long_reach_20": True, "short_reach_20": False,
        },
        {
            "session_date": "2026-08-10", "ticker": "QUIET", "freeze_time": "09:31",
            "previous_close": 3.0, "prior20_median_volume": 350_000,
            "snapshot_price": 3.01, "pm_gap_pct": 0.003, "pm_dollar_volume": 5_000,
            "impulse_pct": 0.003, "open_rvol": 0.8, "open_cum_volume": 3_000,
            "long_reach_20": False, "short_reach_20": False,
        },
        {
            "session_date": "2026-08-10", "ticker": "COLD", "freeze_time": "09:31",
            "previous_close": 4.0, "prior20_median_volume": 300_000,
            "snapshot_price": 3.99, "pm_gap_pct": -0.002, "pm_dollar_volume": 4_000,
            "impulse_pct": -0.003, "open_rvol": 0.7, "open_cum_volume": 2_000,
            "long_reach_20": False, "short_reach_20": True,
        },
    ])


def test_signal_time_selection_is_unchanged_by_future_outcomes():
    a = _snapshots()
    chosen_a = select_signal_time_candidates(a, random_controls=1, max_active=20)

    b = a.copy()
    b["long_reach_20"] = ~b["long_reach_20"]
    b["short_reach_20"] = ~b["short_reach_20"]
    chosen_b = select_signal_time_candidates(b, random_controls=1, max_active=20)

    assert chosen_a[["session_date", "ticker", "selection_role"]].to_dict("records") == chosen_b[["session_date", "ticker", "selection_role"]].to_dict("records")
    assert "HOT" in set(chosen_a.ticker)


def test_signal_time_selection_adds_deterministic_quiet_controls():
    out = select_signal_time_candidates(_snapshots(), random_controls=1, max_active=20)
    assert (out.selection_role == "signal_active").sum() == 1
    assert (out.selection_role == "random_control").sum() == 1
    assert out.ticker.is_unique
