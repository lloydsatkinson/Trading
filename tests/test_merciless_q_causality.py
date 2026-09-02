import pandas as pd

from scanner.strategies.merciless_q.config import MercilessConfig
from scanner.strategies.merciless_q.strategy import generate_merciless_signals


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


def _context(opening_rvol=6.0):
    return {
        "symbol": "AAA",
        "date": "2026-08-28",
        "prior_close": 4.0,
        "market_cap": 200_000_000,
        "pm_gap_pct": 0.15,
        "pm_dollar_turnover": 5_000_000,
        "opening_rvol": opening_rvol,
        "float_shares": 12_000_000,
        "catalyst_class": "NEWS",
        "split": "validation",
    }


def _first_pullback(start_hour=9, start_minute=30):
    base = pd.Timestamp("2026-08-28", tz="America/New_York") + pd.Timedelta(hours=start_hour, minutes=start_minute)
    values = [
        (4.45, 4.55, 4.42, 4.52, 100, 4.49),
        (4.52, 4.90, 4.50, 4.86, 300, 4.71),
        (4.84, 4.88, 4.70, 4.76, 180, 4.74),
        (4.75, 4.79, 4.68, 4.73, 120, 4.73),
        (4.73, 4.78, 4.70, 4.76, 90, 4.74),
        (4.76, 4.91, 4.75, 4.89, 300, 4.84),
        (4.90, 5.05, 4.88, 5.00, 220, 4.96),
    ]
    rows = []
    for i, (o, h, l, c, v, vw) in enumerate(values):
        ts = (base + pd.Timedelta(minutes=i)).strftime("%Y-%m-%d %H:%M")
        rows.append((ts, o, h, l, c, v, vw))
    return _bars(rows)


def _early_vwap_reset():
    return _bars([
        ("2026-08-28 09:30", 4.45, 4.56, 4.42, 4.52, 120, 4.50),
        ("2026-08-28 09:31", 4.52, 5.00, 4.50, 4.95, 420, 4.78),
        ("2026-08-28 09:32", 4.94, 4.96, 4.72, 4.78, 180, 4.82),
        ("2026-08-28 09:33", 4.78, 4.82, 4.61, 4.66, 130, 4.73),
        ("2026-08-28 09:34", 4.66, 4.84, 4.64, 4.82, 270, 4.77),
        ("2026-08-28 09:35", 4.83, 4.98, 4.81, 4.94, 220, 4.91),
    ])


def test_premarket_signal_is_not_emitted_using_end_of_premarket_context():
    out = generate_merciless_signals(
        _first_pullback(start_hour=9, start_minute=20),
        _context(),
        MercilessConfig(min_impulse_pct=0.15),
    )
    assert out.empty


def test_pre_0935_signal_does_not_use_future_opening_rvol_in_gate_or_score():
    cfg = MercilessConfig(min_impulse_pct=0.15, min_breakout_volume_ratio=1.20)
    high_future_rvol = generate_merciless_signals(_early_vwap_reset(), _context(6.0), cfg)
    low_future_rvol = generate_merciless_signals(_early_vwap_reset(), _context(0.5), cfg)

    high = high_future_rvol[high_future_rvol["variant_id"].eq("MMQ_VWAP_RESET")].iloc[0]
    low = low_future_rvol[low_future_rvol["variant_id"].eq("MMQ_VWAP_RESET")].iloc[0]
    assert str(high["signal_timestamp"])[11:16] == "09:34"
    assert high["mmq_score"] == low["mmq_score"]
    assert pd.isna(high["opening_rvol"])
    assert pd.isna(low["opening_rvol"])
    assert high["rvol_bucket"] == "UNKNOWN"
    assert low["rvol_bucket"] == "UNKNOWN"


def test_0935_and_later_signal_applies_completed_opening_rvol_gate():
    out = generate_merciless_signals(
        _first_pullback(),
        _context(0.5),
        MercilessConfig(min_impulse_pct=0.15),
    )
    assert out.empty
