import pandas as pd

from scanner.serclick.pipeline import run_replay_from_cache
from scanner.serclick.replay import ReplayRule
from scripts.run_remote_pipeline import render_news


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


def test_news_surfaces_variable_stop_and_1000_gbp_economics():
    meta = {
        "run_id": "test",
        "start_date": "2026-08-01",
        "end_date": "2026-08-28",
        "sessions": 20,
        "feed": "sip",
        "candidates": 10,
        "ignitions": 3,
        "universe": 1000,
    }
    replay_summary = pd.DataFrame([{
        "variant": "LEO_BOTH_MIDDAY",
        "split": "validation",
        "rule_id": "S50_T30_H60",
        "stop_pct": 0.50,
        "target_pct": 0.30,
        "max_hold_minutes": 60,
        "n": 10,
        "expectancy": 0.04,
        "win_rate": 0.60,
        "profit_factor": 1.80,
        "avg_pnl_gbp_1000": 40.0,
        "planned_stop_gbp_1000": 500.0,
        "worst_pnl_gbp_1000": -500.0,
    }])
    news = render_news(meta, pd.DataFrame(), pd.DataFrame(), replay_summary, pd.DataFrame())
    assert "stop_pct" in news
    assert "avg_pnl_gbp_1000" in news
    assert "planned_stop_gbp_1000" in news
