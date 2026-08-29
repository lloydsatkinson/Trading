import numpy as np
import pandas as pd

from scanner.core.features import (
    attach_session_vwap,
    bucket_gap,
    bucket_rvol,
    bucket_time_of_day,
    close_location_value,
    opening_range,
    prepare_intraday_bars,
    rolling_prior_volume_median,
)


def make_minute_bars(rows, symbol="AAA"):
    records = []
    for ts, o, h, l, c, v, *rest in rows:
        records.append({
            "symbol": symbol,
            "timestamp": pd.Timestamp(ts, tz="America/New_York").tz_convert("UTC"),
            "open": o, "high": h, "low": l, "close": c, "volume": v,
            "vwap": rest[0] if rest else np.nan,
        })
    return pd.DataFrame(records)


def test_opening_range_uses_only_0930_through_0934_bars():
    bars = make_minute_bars([
        ("2026-08-28 09:30", 5.0, 5.2, 4.9, 5.1, 100),
        ("2026-08-28 09:34", 5.1, 5.4, 5.0, 5.3, 200),
        ("2026-08-28 09:35", 5.3, 6.5, 5.2, 6.4, 9999),
    ])
    result = opening_range(bars, minutes=5)
    assert result["high"] == 5.4
    assert result["low"] == 4.9
    assert result["volume"] == 300


def test_prior_volume_median_excludes_current_bar():
    bars = pd.DataFrame({"volume": [10, 20, 30, 40, 50, 1000]})
    out = rolling_prior_volume_median(bars, lookback_bars=5)
    assert out.iloc[-1] == 30


def test_session_vwap_is_cumulative_and_resets_by_symbol_session():
    bars = pd.concat([
        make_minute_bars([
            ("2026-08-28 09:30", 9, 11, 9, 10, 100, 10),
            ("2026-08-28 09:31", 19, 21, 19, 20, 300, 20),
        ], "AAA"),
        make_minute_bars([
            ("2026-08-28 09:30", 29, 31, 29, 30, 100, 30),
        ], "BBB"),
    ], ignore_index=True)
    out = attach_session_vwap(bars)
    aaa = out[out.symbol.eq("AAA")]
    bbb = out[out.symbol.eq("BBB")]
    assert list(aaa["session_vwap"].round(4)) == [10.0, 17.5]
    assert list(bbb["session_vwap"].round(4)) == [30.0]


def test_close_location_value_handles_normal_and_zero_range():
    assert close_location_value({"high": 5.0, "low": 4.0, "close": 5.0}) == 1.0
    assert close_location_value({"high": 5.0, "low": 4.0, "close": 4.0}) == 0.0
    assert close_location_value({"high": 5.0, "low": 5.0, "close": 5.0}) == 0.5


def test_bucket_helpers_are_explicit():
    assert bucket_gap(0.22) == "20%+"
    assert bucket_gap(-0.06) == "5-8%"
    assert bucket_rvol(11) == "10x+"
    assert bucket_time_of_day(pd.Timestamp("2026-08-28 09:40", tz="America/New_York")) == "09:30-10:30"
    assert bucket_time_of_day(pd.Timestamp("2026-08-28 16:30", tz="America/New_York")) == "16:00-20:00"


def test_prepare_intraday_bars_sets_et_and_session_date():
    bars = make_minute_bars([("2026-08-28 09:30", 5, 5, 5, 5, 100)])
    out = prepare_intraday_bars(bars)
    assert str(out.iloc[0]["timestamp_et"].tz) == "America/New_York"
    assert str(out.iloc[0]["session_date"]) == "2026-08-28"
