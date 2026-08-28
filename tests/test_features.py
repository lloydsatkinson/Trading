import pandas as pd

from scanner.serclick.config import SerClickConfig
from scanner.serclick.features import classify_early_day


def make_bars(times, highs, vols, vwaps, closes=None):
    if closes is None:
        closes = highs
    rows = []
    for t, h, v, vw, c in zip(times, highs, vols, vwaps, closes):
        rows.append({"symbol": "TEST", "timestamp": pd.Timestamp(t, tz="America/New_York").tz_convert("UTC"), "open": c, "high": h, "low": min(c, h), "close": c, "volume": v, "trade_count": 10, "vwap": vw})
    return pd.DataFrame(rows)


def test_leo_both_pass():
    cfg = SerClickConfig()
    bars = make_bars(["2026-08-27 08:00", "2026-08-27 09:30"], [2.60, 2.70], [4_200_000, 2_000_000], [2.50, 2.60], [2.55, 2.65])
    q = classify_early_day(bars, prior_close=2.00, cfg=cfg)
    assert q["leo_pm_pass"] is True
    assert q["leo_open_pass"] is True
    assert q["population"] == "BOTH"


def test_open_turnover_does_not_include_premarket():
    cfg = SerClickConfig()
    bars = make_bars(["2026-08-27 08:00", "2026-08-27 09:30"], [2.60, 2.70], [5_000_000, 100_000], [2.50, 2.60], [2.55, 2.65])
    q = classify_early_day(bars, prior_close=2.00, cfg=cfg)
    assert q["leo_pm_pass"] is True
    assert q["leo_open_pass"] is False
    assert q["open30_dollar_turnover"] < 5_000_000
