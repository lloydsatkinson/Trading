import json
from datetime import date

import pandas as pd

from scanner.multistrategy.config import MultiStrategyConfig
from scanner.multistrategy.study import MultiStrategyStudy, broad_candidate_context, dan_candidate_context
from scanner.strategies.dan_irish.config import DanConfig


def early_bars(rows, symbol="AAA"):
    return pd.DataFrame([
        {
            "symbol": symbol,
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


def test_dan_candidate_can_be_above_existing_30_dollar_cap():
    bars = early_bars([
        ("2026-08-28 08:00", 120.0, 125.0, 119.0, 124.0, 10_000, 122.0),
        ("2026-08-28 09:30", 124.0, 126.0, 123.0, 125.0, 5_000, 125.0),
    ])
    dan = dan_candidate_context(bars, prior_close=100.0, cfg=DanConfig())
    broad = broad_candidate_context(bars, prior_close=100.0)
    assert dan["dan_candidate"] is True
    assert dan["price_bucket"] == "GE_100"
    assert broad["broad_candidate"] is False
    assert MultiStrategyConfig().min_price == 1.0
    assert MultiStrategyConfig().max_price == 30.0


class FakeApi:
    def __init__(self):
        self.calls = []

    def stock_bars(self, symbols, timeframe, start, end, feed="sip", adjustment="raw", limit=10_000):
        symbols = list(symbols)
        self.calls.append(symbols)
        rows = []
        for symbol in symbols:
            rows.append({
                "symbol": symbol,
                "timestamp": pd.Timestamp("2026-08-28 09:30", tz="America/New_York").tz_convert("UTC"),
                "open": 4.0,
                "high": 4.2,
                "low": 3.9,
                "close": 4.1,
                "volume": 1000,
                "trade_count": 10,
                "vwap": 4.05,
            })
        return pd.DataFrame(rows)


def test_ensure_minute_day_fetches_only_symbols_missing_from_manifest(tmp_path):
    study = MultiStrategyStudy(root=tmp_path, feed="sip", sessions=1)
    fake = FakeApi()
    study._api = fake

    cache_dir = tmp_path / "data" / "cache" / "multistrategy_alpaca" / "minute"
    cache_dir.mkdir(parents=True)
    cache = cache_dir / "2026-08-28_sip.csv.gz"
    manifest = cache_dir / "2026-08-28_sip.symbols.json"
    pd.DataFrame([{
        "symbol": "AAA",
        "timestamp": pd.Timestamp("2026-08-28 09:30", tz="America/New_York").tz_convert("UTC"),
        "open": 3.0, "high": 3.1, "low": 2.9, "close": 3.0,
        "volume": 500, "trade_count": 5, "vwap": 3.0,
    }]).to_csv(cache, index=False, compression="gzip")
    manifest.write_text(json.dumps(["AAA"]), encoding="utf-8")

    out = study.ensure_minute_day(["AAA", "BBB"], pd.Timestamp("2026-08-28").date())
    assert fake.calls == [["BBB"]]
    assert set(out["symbol"]) == {"AAA", "BBB"}
    assert set(json.loads(manifest.read_text(encoding="utf-8"))) == {"AAA", "BBB"}


def test_native_study_returns_separate_dan_contexts_and_fetches_union_once(tmp_path, monkeypatch):
    study = MultiStrategyStudy(root=tmp_path, feed="sip", sessions=1)
    day = date(2026, 8, 28)
    monkeypatch.setattr(study, "_completed_sessions", lambda: [day])
    monkeypatch.setattr(study, "_assets", lambda: pd.DataFrame({"symbol": ["AAA", "BBB"]}))

    daily = pd.concat([
        early_bars([("2026-08-27 16:00", 4.0, 4.0, 4.0, 4.0, 1000, 4.0)], symbol="AAA"),
        early_bars([("2026-08-27 16:00", 100.0, 100.0, 100.0, 100.0, 1000, 100.0)], symbol="BBB"),
    ], ignore_index=True)
    monkeypatch.setattr(study, "_daily_bars", lambda symbols, sessions: daily.copy())
    monkeypatch.setattr(study, "_prior_close_map", lambda frame: {("AAA", day): 4.0, ("BBB", day): 100.0})

    early = pd.concat([
        early_bars([
            ("2026-08-28 08:00", 4.30, 4.40, 4.25, 4.40, 300_000, 4.35),
            ("2026-08-28 09:30", 4.40, 4.45, 4.38, 4.42, 100_000, 4.41),
        ], symbol="AAA"),
        early_bars([
            ("2026-08-28 08:00", 120.0, 125.0, 119.0, 124.0, 10_000, 122.0),
            ("2026-08-28 09:30", 124.0, 126.0, 123.0, 125.0, 5_000, 125.0),
        ], symbol="BBB"),
    ], ignore_index=True)
    monkeypatch.setattr(study, "_fetch_early_day", lambda symbols, session: early.copy())
    monkeypatch.setattr(study, "_fetch_opening_history", lambda symbols, sessions, through_day: pd.DataFrame())
    monkeypatch.setattr("scanner.serclick.marketcap.load_or_fetch_market_cap_snapshot", lambda root, session: pd.DataFrame())

    union_calls = []

    def ensure_union(symbols, session):
        union_calls.append(tuple(sorted(symbols)))
        return pd.concat([
            early_bars([("2026-08-28 09:30", 4.40, 4.45, 4.38, 4.42, 100_000, 4.41)], symbol="AAA"),
            early_bars([("2026-08-28 09:30", 124.0, 126.0, 123.0, 125.0, 5_000, 125.0)], symbol="BBB"),
        ], ignore_index=True)

    monkeypatch.setattr(study, "ensure_minute_day", ensure_union)

    meta = study.run(include_dan_candidates=True)

    assert set(meta["candidate_contexts"]["symbol"]) == {"AAA"}
    assert set(meta["dan_candidate_contexts"]["symbol"]) == {"BBB"}
    assert union_calls == [("AAA", "BBB")]
    assert meta["daily_bars"].equals(daily)
    assert meta["split_end_dates"] == {"development": "2026-08-28"}
