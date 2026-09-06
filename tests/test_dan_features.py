import numpy as np
import pandas as pd

from scanner.core.models import price_bucket
from scanner.strategies.dan_irish.features import retained_gain_checkpoint_values, retained_gain_ratio


def test_dan_price_bucket_boundaries():
    assert price_bucket(0.99) == "LT_1"
    assert price_bucket(1.00) == "1_2"
    assert price_bucket(1.99) == "1_2"
    assert price_bucket(2.00) == "2_5"
    assert price_bucket(5.00) == "5_10"
    assert price_bucket(10.00) == "10_20"
    assert price_bucket(20.00) == "20_50"
    assert price_bucket(50.00) == "50_100"
    assert price_bucket(100.00) == "GE_100"
    assert price_bucket(None) == "UNKNOWN"
    assert price_bucket(0) == "UNKNOWN"


def test_retained_gain_ratio_and_invalid_denominator():
    assert retained_gain_ratio(2.0, 6.0, 5.0) == 0.75
    assert np.isnan(retained_gain_ratio(4.0, 4.0, 4.0))
    assert np.isnan(retained_gain_ratio(None, 6.0, 5.0))


def _checkpoint_bars(late_close=5.8):
    rows = [
        ("2026-08-28 09:30", 5.0),
        ("2026-08-28 09:40", 5.6),
        ("2026-08-28 09:50", 5.4),
        ("2026-08-28 10:00", 5.2),
        ("2026-08-28 10:30", 5.0),
        ("2026-08-28 11:00", 4.8),
        ("2026-08-28 11:30", late_close),
    ]
    return pd.DataFrame([
        {
            "symbol": "AAA",
            "timestamp": pd.Timestamp(ts, tz="America/New_York").tz_convert("UTC"),
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "volume": 100,
            "vwap": close,
        }
        for ts, close in rows
    ])


def test_retained_gain_checkpoint_values_are_timestamp_bounded():
    out = retained_gain_checkpoint_values(
        _checkpoint_bars(),
        impulse_timestamp="2026-08-28 09:30-04:00",
        impulse_start_price=4.0,
        impulse_high_price=6.0,
    )
    assert np.isclose(out["retained_gain_10m"], 0.80)
    assert np.isclose(out["retained_gain_20m"], 0.70)
    assert np.isclose(out["retained_gain_30m"], 0.60)
    assert np.isclose(out["retained_gain_60m"], 0.50)
    assert np.isclose(out["retained_gain_90m"], 0.40)


def test_later_bars_cannot_change_earlier_retained_gain_checkpoint():
    first = retained_gain_checkpoint_values(
        _checkpoint_bars(late_close=5.8),
        impulse_timestamp="2026-08-28 09:30-04:00",
        impulse_start_price=4.0,
        impulse_high_price=6.0,
    )
    changed = retained_gain_checkpoint_values(
        _checkpoint_bars(late_close=99.0),
        impulse_timestamp="2026-08-28 09:30-04:00",
        impulse_start_price=4.0,
        impulse_high_price=6.0,
    )
    assert first["retained_gain_10m"] == changed["retained_gain_10m"]
    assert first["retained_gain_90m"] == changed["retained_gain_90m"]
