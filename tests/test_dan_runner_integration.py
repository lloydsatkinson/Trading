import json
from pathlib import Path

import pandas as pd

import scripts.run_strategy_research as runner
from scanner.core.multisession_replay import SwingReplayRule


def _bars(day, rows):
    return pd.DataFrame([
        {
            "symbol": "AAA",
            "timestamp": pd.Timestamp(f"{day} {hhmm}", tz="America/New_York").tz_convert("UTC"),
            "open": o,
            "high": h,
            "low": l,
            "close": c,
            "volume": v,
            "vwap": vw,
        }
        for hhmm, o, h, l, c, v, vw in rows
    ])


def _day0_minutes():
    rows = [("09:30", 4.50, 5.00, 4.45, 4.90, 1000, 4.80)]
    for minute in range(31, 41):
        rows.append((f"09:{minute}", 4.82, 4.92, 4.70, 4.84, 100, 4.82))
    rows += [
        ("09:41", 4.86, 5.12, 4.84, 5.05, 300, 4.96),
        ("09:42", 5.06, 5.18, 5.02, 5.14, 180, 5.07),
    ]
    return _bars("2026-08-28", rows)


def _day1_minutes():
    rows = []
    for minute in range(30, 40):
        rows.append((f"09:{minute}", 5.10, 5.20, 5.00, 5.12, 100, 5.10))
    rows += [
        ("09:40", 5.13, 5.30, 5.10, 5.25, 250, 5.18),
        ("09:41", 5.26, 5.34, 5.20, 5.30, 180, 5.24),
        ("15:59", 5.20, 5.28, 5.15, 5.22, 100, 5.20),
    ]
    return _bars("2026-08-31", rows)


def _day2_minutes():
    return _bars("2026-09-01", [
        ("09:30", 5.25, 5.45, 5.22, 5.40, 250, 5.32),
        ("09:31", 5.41, 5.52, 5.36, 5.48, 180, 5.42),
        ("15:59", 5.42, 5.50, 5.38, 5.45, 100, 5.43),
    ])


def _day3_minutes():
    return _bars("2026-09-02", [
        ("09:30", 5.46, 5.58, 5.40, 5.52, 180, 5.48),
        ("15:59", 5.55, 5.65, 5.50, 5.60, 120, 5.56),
    ])


def _daily_bars():
    rows = [
        ("2026-08-28", 4.50, 5.20, 4.40, 5.00, 2_000_000, 4.85),
        ("2026-08-31", 5.10, 5.30, 5.00, 5.20, 1_000_000, 5.16),
        ("2026-09-01", 5.25, 5.50, 5.20, 5.45, 900_000, 5.38),
        ("2026-09-02", 5.46, 5.65, 5.40, 5.60, 850_000, 5.54),
    ]
    return pd.DataFrame([
        {
            "symbol": "AAA",
            "timestamp": pd.Timestamp(f"{day} 16:00", tz="America/New_York").tz_convert("UTC"),
            "open": o, "high": h, "low": l, "close": c, "volume": v, "vwap": vw,
        }
        for day, o, h, l, c, v, vw in rows
    ])


def _dan_contexts():
    return pd.DataFrame([{
        "symbol": "AAA",
        "date": "2026-08-28",
        "split": "validation",
        "feed": "SIP",
        "prior_close": 4.00,
        "dan_candidate": True,
        "price_bucket": "2_5",
        "pm_gap_pct": 0.20,
        "pm_dollar_turnover": 2_000_000.0,
        "opening_rvol": 6.0,
        "market_cap": 200_000_000.0,
        "market_cap_bucket": "MICROCAP",
        "float_shares": 12_000_000.0,
        "catalyst_class": "NEWS",
    }])


class _FakeDanStudy:
    def __init__(self, root=".", feed="sip", sessions=60, end_date=None):
        self.root = Path(root)
        self.feed = feed
        self.sessions = sessions
        self.end_date = end_date

    def run(self, include_dan_candidates=False):
        assert include_dan_candidates is True
        return {
            "run_id": "synthetic_dan",
            "feed": self.feed.upper(),
            "sessions": 4,
            "start_date": "2026-08-28",
            "end_date": "2026-09-02",
            "candidate_contexts": pd.DataFrame(),
            "dan_candidate_contexts": _dan_contexts(),
            "daily_bars": _daily_bars(),
            "split_end_dates": {"validation": "2026-09-02"},
            "minute_files": [],
            "output_dir": str(self.root / "data" / "research" / "multistrategy" / "synthetic_dan"),
        }

    def ensure_minute_day(self, symbols, day):
        path = self.root / "data" / "cache" / "multistrategy_alpaca" / "minute" / f"{day}_{self.feed}.csv.gz"
        return pd.read_csv(path) if path.exists() else pd.DataFrame()


def _blocked_http(*args, **kwargs):
    raise AssertionError("API-free Dan smoke test attempted an HTTP request")


def _integration_rules(signal):
    # The complete 455-rule Dan grid is asserted independently in
    # test_dan_reporting.py. The integration smoke only needs representative
    # 1- and 2-session rules to prove the runner uses real swing replay/censoring.
    return [
        SwingReplayRule(stop_pct=0.08, target_r_multiple=2.0, max_hold_sessions=1),
        SwingReplayRule(stop_pct=0.08, target_r_multiple=2.0, max_hold_sessions=2),
    ]


def test_parse_strategies_supports_dan_and_all():
    assert runner._parse_strategies("dan") == ("dan",)
    assert "dan" in runner._parse_strategies("all")


def test_api_free_dan_runner_executes_intraday_and_swing_paths(tmp_path, monkeypatch):
    cache = tmp_path / "data" / "cache" / "multistrategy_alpaca" / "minute"
    cache.mkdir(parents=True)
    for day, frame in {
        "2026-08-28": _day0_minutes(),
        "2026-08-31": _day1_minutes(),
        "2026-09-01": _day2_minutes(),
        "2026-09-02": _day3_minutes(),
    }.items():
        frame.to_csv(cache / f"{day}_sip.csv.gz", index=False, compression="gzip")

    monkeypatch.setattr(runner, "MultiStrategyStudy", _FakeDanStudy)
    monkeypatch.setattr("scanner.strategies.dan_irish.research.default_dan_swing_rules", _integration_rules)
    monkeypatch.setattr("requests.sessions.Session.request", _blocked_http)

    result = runner.run_research(
        root=tmp_path,
        feed="sip",
        sessions=4,
        end_date="2026-09-02",
        strategies=("dan",),
        min_n=1,
    )

    assert not result.signals.empty
    assert set(result.signals["strategy_id"]) == {"DAN_IRISH"}
    assert {"intraday", "swing"}.issubset(set(result.signals["_replay_mode"]))
    assert not result.replays.empty
    assert not result.price_bucket_summary.empty
    assert not result.swing_hold_summary.empty
    assert not result.censor_summary.empty
    assert not result.dan_threshold_summary.empty

    dan_replays = result.replays[result.replays["strategy_id"].eq("DAN_IRISH")]
    assert "exit_rule_id" in dan_replays.columns
    assert dan_replays["rule_id"].astype(str).str.contains("__", regex=False).all()

    expected = {
        "price_bucket_summary.csv",
        "retained_gain_summary.csv",
        "swing_hold_summary.csv",
        "overnight_gap_risk.csv",
        "censor_summary.csv",
        "dan_threshold_summary.csv",
    }
    assert expected.issubset({path.name for path in result.output_dir.iterdir()})
    assert (tmp_path / "data" / "latest" / "dan_threshold_summary.csv").exists()

    meta = json.loads((result.output_dir / "run_meta.json").read_text(encoding="utf-8"))
    assert meta["market_data_adjustment"] == "raw"
