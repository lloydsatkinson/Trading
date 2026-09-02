import math

import pandas as pd

from scanner.strategies.dan_irish.config import DanConfig
from scanner.strategies.dan_irish.intraday import generate_dan_intraday_signals


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


def _context():
    return {
        "symbol": "AAA",
        "date": "2026-08-28",
        "prior_close": 4.0,
        "dan_candidate": True,
        "pm_gap_pct": 0.20,
        "pm_dollar_turnover": 8_000_000.0,
        "opening_rvol": 8.0,
        "market_cap": 200_000_000.0,
        "float_shares": 12_000_000.0,
        "catalyst_class": "NEWS",
        "split": "validation",
    }


def test_intraday_impulse_anchors_to_true_pre_base_peak_not_first_threshold_crossing():
    fixture = _bars([
        # First bar merely crosses the +20% minimum extension.
        ("2026-08-28 09:30", 4.50, 4.85, 4.45, 4.80, 500, 4.70),
        # The initial impulse actually continues to 5.20 before a real base forms.
        ("2026-08-28 09:31", 4.82, 5.20, 4.80, 5.10, 700, 5.00),
        ("2026-08-28 09:32", 5.08, 5.12, 4.95, 5.00, 120, 5.02),
        ("2026-08-28 09:33", 5.00, 5.08, 4.90, 4.98, 110, 4.99),
        ("2026-08-28 09:34", 4.98, 5.06, 4.94, 5.02, 100, 5.00),
        # Confirmation breaks the completed base, then entry is next bar.
        ("2026-08-28 09:35", 5.03, 5.24, 5.02, 5.22, 600, 5.15),
        ("2026-08-28 09:36", 5.23, 5.30, 5.18, 5.26, 300, 5.24),
    ])

    out = generate_dan_intraday_signals(
        fixture,
        _context(),
        DanConfig(
            min_reference_extension_pct=0.20,
            min_consolidation_minutes=3,
            min_retained_gain=0.60,
            max_pullback_depth=0.50,
            min_breakout_volume_ratio=1.5,
        ),
    )

    assert len(out) == 1
    row = out.iloc[0]
    assert row["impulse_high"] == 5.20
    assert row["base_low"] == 4.90
    assert math.isclose(row["retained_gain_ratio"], 0.75, rel_tol=1e-12)
    assert math.isclose(row["pullback_depth"], 0.25, rel_tol=1e-12)
    assert str(row["signal_timestamp"])[11:16] == "09:35"
    assert str(row["entry_timestamp"])[11:16] == "09:36"
