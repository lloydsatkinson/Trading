import pandas as pd

from scanner.multistrategy.study import broad_candidate_context, opening_baseline_for_day


def early_bars(rows):
    return pd.DataFrame([
        {
            "symbol": "AAA",
            "timestamp": pd.Timestamp(ts, tz="America/New_York").tz_convert("UTC"),
            "open": o,
            "high": h,
            "low": l,
            "close": c,
            "volume": v,
            "vwap": vw,
        }
        for ts, o, h, l, c, v, vw in rows
    ])


def test_ten_percent_high_turnover_gap_can_be_broad_candidate_without_leo_extension():
    bars = early_bars([
        ("2026-08-28 08:00", 4.30, 4.42, 4.28, 4.40, 600_000, 4.36),
        ("2026-08-28 08:30", 4.40, 4.44, 4.38, 4.41, 100_000, 4.41),
        ("2026-08-28 09:30", 4.42, 4.50, 4.40, 4.48, 200_000, 4.46),
    ])
    ctx = broad_candidate_context(bars, prior_close=4.0)
    assert ctx["broad_candidate"] is True
    assert 0.09 <= ctx["pm_gap_pct"] <= 0.12
    assert ctx["pm_dollar_turnover"] > 1_000_000
    assert ctx["pm_high"] / 4.0 < 1.20
    assert ctx["leo_extension_runner"] is False


def test_broad_candidate_can_use_regular_open_gap_when_no_premarket_prints():
    bars = early_bars([
        ("2026-08-28 09:30", 4.40, 4.50, 4.35, 4.45, 300_000, 4.43),
        ("2026-08-28 09:31", 4.45, 4.55, 4.40, 4.50, 300_000, 4.49),
    ])
    ctx = broad_candidate_context(bars, prior_close=4.0)
    assert ctx["broad_candidate"] is True
    assert round(ctx["pm_gap_pct"], 4) == 0.10
    assert ctx["pm_volume"] == 0.0


def test_opening_baseline_excludes_current_day_and_uses_only_prior_20_sessions():
    dates = pd.bdate_range("2026-07-29", periods=22).date
    history = pd.DataFrame([
        {"symbol": "AAA", "date": str(day), "opening5_volume": 100 + i, "opening5_dollar_turnover": 1000 + i}
        for i, day in enumerate(dates)
    ])
    current_day = dates[-1]
    history.loc[history["date"].eq(str(current_day)), "opening5_volume"] = 1_000_000
    baseline = opening_baseline_for_day(history, "AAA", current_day, lookback_sessions=20)
    prior = history[history["date"].lt(str(current_day))].tail(20)
    assert baseline["history_n"] == 20
    assert baseline["median_opening5_volume"] == prior["opening5_volume"].median()
    assert baseline["median_opening5_volume"] < 1000


def test_opening_baseline_does_not_use_future_rows():
    history = pd.DataFrame([
        {"symbol":"AAA", "date":"2026-08-27", "opening5_volume":100, "opening5_dollar_turnover":1000},
        {"symbol":"AAA", "date":"2026-08-28", "opening5_volume":200, "opening5_dollar_turnover":2000},
        {"symbol":"AAA", "date":"2026-08-31", "opening5_volume":999999, "opening5_dollar_turnover":9999999},
    ])
    baseline = opening_baseline_for_day(history, "AAA", "2026-08-28")
    assert baseline["history_n"] == 1
    assert baseline["median_opening5_volume"] == 100


def test_missing_optional_float_and_news_are_explicit_unknowns():
    bars = early_bars([
        ("2026-08-28 08:00", 4.30, 4.45, 4.28, 4.40, 500_000, 4.36),
        ("2026-08-28 09:30", 4.42, 4.50, 4.40, 4.48, 200_000, 4.46),
    ])
    ctx = broad_candidate_context(bars, prior_close=4.0)
    assert ctx["float_shares"] is None
    assert ctx["catalyst_class"] == "UNKNOWN"
