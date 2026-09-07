import pandas as pd

from scanner.strategies.merciless_q.config import MercilessConfig
from scanner.strategies.merciless_q.strategy import generate_merciless_signals


def _bars():
    rows = [
        ("09:30", 4.45, 4.58, 4.42, 4.54, 120, 4.50),
        ("09:31", 4.54, 4.92, 4.52, 4.88, 360, 4.75),
        ("09:32", 4.86, 4.94, 4.78, 4.90, 150, 4.87),
        ("09:33", 4.88, 4.93, 4.80, 4.89, 120, 4.87),
        ("09:34", 4.87, 4.94, 4.82, 4.91, 110, 4.89),
        ("09:35", 4.91, 5.02, 4.90, 5.00, 300, 4.97),
        ("09:36", 5.01, 5.12, 4.99, 5.08, 210, 5.06),
        ("09:37", 5.08, 5.10, 4.95, 4.99, 130, 5.01),
        ("09:38", 4.99, 5.04, 4.94, 5.01, 100, 4.99),
        ("09:39", 5.01, 5.07, 4.98, 5.05, 90, 5.02),
        ("09:40", 5.05, 5.18, 5.04, 5.16, 320, 5.12),
        ("09:41", 5.17, 5.28, 5.14, 5.24, 220, 5.21),
        ("09:42", 5.23, 5.25, 5.10, 5.14, 120, 5.17),
        ("09:43", 5.14, 5.19, 5.09, 5.16, 100, 5.14),
        ("09:44", 5.16, 5.22, 5.12, 5.20, 90, 5.17),
        ("09:45", 5.20, 5.34, 5.19, 5.32, 310, 5.28),
        ("09:46", 5.33, 5.45, 5.30, 5.41, 210, 5.38),
    ]
    return pd.DataFrame([
        {
            "symbol": "AAA",
            "timestamp": pd.Timestamp(f"2026-08-28 {ts}", tz="America/New_York").tz_convert("UTC"),
            "open": o, "high": h, "low": l, "close": c, "volume": v, "vwap": vw,
        }
        for ts, o, h, l, c, v, vw in rows
    ])


def _context():
    return {
        "symbol": "AAA", "date": "2026-08-28", "prior_close": 4.0,
        "market_cap": 200_000_000, "pm_gap_pct": 0.15,
        "pm_dollar_turnover": 5_000_000, "opening_rvol": 6.0,
        "float_shares": 12_000_000, "catalyst_class": "NEWS", "split": "forward",
    }


def test_repeated_entries_are_sequenced_and_physically_separated():
    cfg = MercilessConfig(
        min_impulse_pct=0.15,
        min_breakout_volume_ratio=1.20,
        cooldown_bars=3,
        max_signals_per_symbol=8,
    )
    out = generate_merciless_signals(_bars(), _context(), cfg)
    assert len(out) >= 2
    assert out["sequence_number"].tolist() == list(range(1, len(out) + 1))
    assert out["signal_timestamp"].is_unique
    assert out.iloc[1:]["minutes_since_prior_signal"].min() >= 3.0


def test_repeated_entries_respect_symbol_cap():
    cfg = MercilessConfig(
        min_impulse_pct=0.15,
        min_breakout_volume_ratio=1.20,
        cooldown_bars=2,
        max_signals_per_symbol=2,
    )
    out = generate_merciless_signals(_bars(), _context(), cfg)
    assert len(out) == 2
    assert out["sequence_number"].tolist() == [1, 2]
