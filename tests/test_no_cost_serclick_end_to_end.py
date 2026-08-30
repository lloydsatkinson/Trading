import pandas as pd

import scripts.run_strategy_research as runner
from scanner.strategies.serclick_leo.strategy import adapt_serclick_ignitions


def _blocked_http(*args, **kwargs):
    raise AssertionError("SerClick API-free smoke test attempted an HTTP request")


def _normalized_serclick_signal():
    ignition = pd.DataFrame([{
        "symbol": "AAA",
        "date": "2026-08-27",
        "split": "validation",
        "population": "BOTH",
        "ignition_window": "10:30-15:00",
        "timestamp": pd.Timestamp("2026-08-27 11:00", tz="America/New_York"),
        "entry_timestamp": pd.Timestamp("2026-08-27 11:01", tz="America/New_York"),
        "entry_raw_open": 4.00,
        "entry_price_slipped": 4.01,
        "market_cap": 75_000_000.0,
        "market_cap_bucket": "MICROCAP",
    }])
    signals = adapt_serclick_ignitions(ignition)
    signals["_cache_namespace"] = "serclick_alpaca"
    return signals


def _minute_bars():
    rows = [
        ("11:01", 4.00, 4.08, 3.96, 4.05, 500),
        ("11:02", 4.05, 4.18, 4.02, 4.15, 600),
        ("11:03", 4.15, 4.30, 4.10, 4.25, 700),
        ("11:04", 4.25, 4.42, 4.20, 4.38, 800),
        ("11:05", 4.38, 4.55, 4.30, 4.50, 900),
    ]
    return pd.DataFrame([
        {
            "symbol": "AAA",
            "timestamp": pd.Timestamp(f"2026-08-27 {hhmm}", tz="America/New_York").tz_convert("UTC"),
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "vwap": close,
        }
        for hhmm, open_, high, low, close, volume in rows
    ])


def test_api_free_serclick_adapter_replay_and_reporting_path(tmp_path, monkeypatch):
    cache = tmp_path / "data" / "cache" / "serclick_alpaca" / "minute"
    cache.mkdir(parents=True)
    _minute_bars().to_csv(cache / "2026-08-27_sip.csv.gz", index=False, compression="gzip")

    def fake_signal_sets(root, feed, requested_end_date):
        return _normalized_serclick_signal(), [{
            "run_id": "synthetic_serclick_no_cost",
            "feed": "SIP",
            "start_date": "2026-08-27",
            "end_date": "2026-08-27",
            "output_dir": "synthetic",
        }]

    monkeypatch.setattr(runner, "_serclick_signal_sets", fake_signal_sets)
    monkeypatch.setattr("requests.sessions.Session.request", _blocked_http)

    result = runner.run_research(
        root=tmp_path,
        feed="sip",
        sessions=1,
        end_date="2026-08-27",
        strategies=("serclick",),
        min_n=1,
    )

    assert not result.signals.empty
    signal = result.signals.iloc[0]
    assert signal["strategy_id"] == "SERCLICK_LEO"
    assert signal["variant_id"] == "LEO_BOTH_MIDDAY"
    assert signal["direction"] == "LONG"
    assert signal["entry_price_raw"] == 4.0
    assert signal["split"] == "validation"

    assert not result.replays.empty
    assert set(result.replays["slippage_bps"]) == {10.0, 25.0, 50.0, 75.0, 100.0}
    assert set(result.replays["strategy_id"]) == {"SERCLICK_LEO"}
    assert not result.summary.empty
    assert not result.leaderboard.empty
    assert not result.best_hold_times.empty
