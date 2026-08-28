import pandas as pd

from scanner.serclick.pipeline import run_replay_from_cache
from scanner.serclick.replay import ReplayRule


def test_run_replay_from_cache_uses_symbol_day_cache(tmp_path):
    cache_dir = tmp_path / "data" / "cache" / "serclick_alpaca" / "minute"
    cache_dir.mkdir(parents=True)
    bars = pd.DataFrame([
        {"symbol": "AAA", "timestamp": "2026-08-27T14:31:00Z", "open": 10.0, "high": 10.4, "low": 9.9, "close": 10.2, "volume": 1000, "trade_count": 10, "vwap": 10.1},
        {"symbol": "AAA", "timestamp": "2026-08-27T14:32:00Z", "open": 10.2, "high": 11.1, "low": 10.1, "close": 11.0, "volume": 1200, "trade_count": 12, "vwap": 10.7},
    ])
    bars.to_csv(cache_dir / "2026-08-27_sip.csv.gz", index=False, compression="gzip")
    ignitions = pd.DataFrame([{
        "symbol": "AAA",
        "date": "2026-08-27",
        "split": "validation",
        "population": "BOTH",
        "ignition_window": "10:30-15:00",
        "entry_timestamp": "2026-08-27 10:31:00-04:00",
        "entry_price_slipped": 10.0,
    }])
    out = run_replay_from_cache(root=tmp_path, feed="sip", ignitions=ignitions, rules=[ReplayRule(0.05, 0.10, 60)])
    midday = out[out["variant"].eq("LEO_BOTH_MIDDAY")]
    assert len(midday) == 1
    assert midday.iloc[0]["exit_reason"] == "TARGET"
    assert midday.iloc[0]["return_pct"] == 0.10
