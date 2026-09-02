import pandas as pd

from scanner.strategies.dan_irish.config import DanConfig
from scanner.strategies.dan_irish.intraday import (
    generate_dan_intraday_signals,
    _generate_dan_intraday_signal_grid_optimized,
)


def _bars():
    rows = [
        ("2026-08-28 09:30", 4.40, 4.85, 4.35, 4.75, 500, 4.65),
        ("2026-08-28 09:31", 4.72, 4.78, 4.65, 4.70, 100, 4.70),
        ("2026-08-28 09:32", 4.70, 4.75, 4.62, 4.68, 100, 4.68),
        ("2026-08-28 09:33", 4.68, 4.74, 4.64, 4.71, 100, 4.69),
        ("2026-08-28 09:34", 4.72, 4.90, 4.70, 4.87, 120, 4.80),
        ("2026-08-28 09:35", 4.88, 5.02, 4.84, 4.99, 260, 4.91),
        ("2026-08-28 09:36", 5.00, 5.12, 4.96, 5.08, 320, 5.03),
        ("2026-08-28 09:37", 5.09, 5.15, 5.02, 5.11, 180, 5.09),
    ]
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
        "pm_high": 4.80,
        "pm_gap_pct": 0.15,
        "pm_dollar_turnover": 5_000_000.0,
        "opening_rvol": 6.0,
        "market_cap": 200_000_000.0,
        "float_shares": 12_000_000.0,
        "catalyst_class": "NEWS",
        "split": "validation",
    }


def _reference_grid(bars, context, cfg, minutes_grid, references, ratios):
    frames = []
    for minutes in minutes_grid:
        for reference in references:
            for ratio in ratios:
                combo = DanConfig(
                    min_reference_extension_pct=cfg.min_reference_extension_pct,
                    min_activity_dollar_turnover=cfg.min_activity_dollar_turnover,
                    min_retained_gain=cfg.min_retained_gain,
                    min_consolidation_minutes=int(minutes),
                    max_pullback_depth=cfg.max_pullback_depth,
                    min_breakout_volume_ratio=float(ratio),
                    volume_lookback_bars=cfg.volume_lookback_bars,
                    slippage_bps=cfg.slippage_bps,
                    followup_sessions=cfg.followup_sessions,
                )
                out = generate_dan_intraday_signals(
                    bars,
                    context,
                    combo,
                    breakout_reference=reference,
                )
                if not out.empty:
                    frames.append(out)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True, sort=False).drop_duplicates(
        subset=["symbol", "entry_timestamp", "setup_id"], keep="first"
    ).reset_index(drop=True)


def test_optimized_intraday_grid_matches_independent_combo_replays():
    bars = _bars()
    context = _context()
    cfg = DanConfig(
        min_reference_extension_pct=0.20,
        min_retained_gain=0.60,
        max_pullback_depth=0.50,
    )
    minutes_grid = (3, 4)
    references = ("BASE_HIGH", "HOD", "PM_HIGH")
    ratios = (1.0, 1.5, 2.0)

    expected = _reference_grid(bars, context, cfg, minutes_grid, references, ratios)
    actual = _generate_dan_intraday_signal_grid_optimized(
        bars,
        context,
        cfg,
        consolidation_minutes=minutes_grid,
        breakout_references=references,
        volume_ratios=ratios,
    )

    assert not expected.empty
    compare = [
        "setup_id",
        "signal_timestamp",
        "entry_timestamp",
        "entry_price_raw",
        "stop_reference",
        "impulse_pct",
        "impulse_high",
        "base_low",
        "base_high",
        "retained_gain_ratio",
        "pullback_depth",
        "breakout_volume_ratio",
        "breakout_reference_type",
        "breakout_level",
        "price_bucket",
        "split",
        "attribution",
        "_replay_mode",
    ]
    left = actual[compare].sort_values("setup_id").reset_index(drop=True)
    right = expected[compare].sort_values("setup_id").reset_index(drop=True)
    pd.testing.assert_frame_equal(left, right, check_dtype=False)
