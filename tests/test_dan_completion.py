import numpy as np
import pandas as pd

from scanner.strategies.dan_irish.config import DanConfig
from scanner.strategies.dan_irish.intraday import (
    generate_dan_intraday_signal_grid,
    generate_dan_intraday_signals,
)


def _bars(rows):
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


def _context(**overrides):
    out = {
        "symbol": "AAA",
        "date": "2026-08-28",
        "prior_close": 4.0,
        "dan_candidate": True,
        "pm_high": 4.80,
        "pm_gap_pct": 0.15,
        "pm_dollar_turnover": 5_000_000.0,
        "opening_rvol": 6.0,
        "market_cap": 200_000_000.0,
        "float_shares": 12_000_000.0,
        "catalyst_class": "NEWS",
        "split": "validation",
    }
    out.update(overrides)
    return out


def _extended_fixture():
    rows = [
        ("2026-08-28 09:30", 4.40, 4.85, 4.35, 4.75, 500, 4.65),
        ("2026-08-28 09:31", 4.72, 4.78, 4.65, 4.70, 100, 4.70),
        ("2026-08-28 09:32", 4.70, 4.75, 4.62, 4.68, 100, 4.68),
        ("2026-08-28 09:33", 4.68, 4.74, 4.64, 4.71, 100, 4.69),
        ("2026-08-28 09:34", 4.72, 4.82, 4.70, 4.80, 300, 4.76),
        ("2026-08-28 09:35", 4.81, 5.00, 4.79, 4.95, 400, 4.90),
    ]
    for minute in range(36, 62):
        price = 4.90 - 0.01 * min(minute - 36, 10)
        rows.append((f"2026-08-28 09:{minute:02d}" if minute < 60 else f"2026-08-28 10:{minute-60:02d}", price, price + 0.03, price - 0.03, price, 120, price))
    return _bars(rows)


def test_intraday_signal_persists_retained_gain_checkpoints():
    out = generate_dan_intraday_signals(
        _extended_fixture(),
        _context(),
        DanConfig(
            min_reference_extension_pct=0.20,
            min_consolidation_minutes=3,
            min_retained_gain=0.60,
            min_breakout_volume_ratio=1.5,
        ),
    )
    row = out.iloc[0]
    for column in (
        "retained_gain_10m",
        "retained_gain_20m",
        "retained_gain_30m",
        "retained_gain_60m",
        "retained_gain_90m",
    ):
        assert column in out.columns
    assert np.isfinite(row["retained_gain_10m"])


def test_intraday_grid_keeps_entry_hypotheses_separate():
    out = generate_dan_intraday_signal_grid(
        _extended_fixture(),
        _context(),
        DanConfig(min_reference_extension_pct=0.20, min_retained_gain=0.60),
        consolidation_minutes=(3,),
        breakout_references=("BASE_HIGH", "PM_HIGH"),
        volume_ratios=(1.0, 1.5),
    )
    assert not out.empty
    expected = {
        "C3_BASE_HIGH_V1P0",
        "C3_BASE_HIGH_V1P5",
        "C3_PM_HIGH_V1P0",
        "C3_PM_HIGH_V1P5",
    }
    assert expected.issubset(set(out["setup_id"]))
    assert out["setup_id"].nunique() >= 4
