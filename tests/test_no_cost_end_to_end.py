from pathlib import Path

import pandas as pd

import scripts.run_strategy_research as runner


def _minute_bars() -> pd.DataFrame:
    rows = [
        ("09:30", 4.40, 4.45, 4.35, 4.42, 100),
        ("09:31", 4.42, 4.46, 4.40, 4.44, 100),
        ("09:32", 4.44, 4.47, 4.41, 4.45, 100),
        ("09:33", 4.45, 4.48, 4.42, 4.46, 100),
        ("09:34", 4.46, 4.49, 4.43, 4.47, 100),
        ("09:35", 4.47, 4.70, 4.46, 4.68, 1000),
        ("09:36", 4.69, 4.80, 4.60, 4.75, 300),
        ("09:37", 4.75, 5.00, 4.70, 4.95, 300),
        ("09:38", 4.95, 5.20, 4.90, 5.10, 300),
        ("09:39", 5.10, 5.30, 5.00, 5.20, 300),
    ]
    out = []
    for hhmm, open_, high, low, close, volume in rows:
        ts = pd.Timestamp(f"2026-08-28 {hhmm}", tz="America/New_York").tz_convert("UTC")
        out.append({
            "symbol": "AAA",
            "timestamp": ts,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "vwap": close,
        })
    return pd.DataFrame(out)


def _context() -> pd.DataFrame:
    return pd.DataFrame([{
        "symbol": "AAA",
        "date": "2026-08-28",
        "split": "validation",
        "feed": "SIP",
        "prior_close": 4.00,
        "pm_gap_pct": 0.10,
        "pm_dollar_turnover": 2_000_000.0,
        "opening_rvol": 5.0,
        "market_cap": 100_000_000.0,
        "market_cap_bucket": "MICROCAP",
        "float_shares": 8_000_000.0,
        "catalyst_class": "UNKNOWN",
    }])


class _FakeStudy:
    def __init__(self, root=".", feed="sip", sessions=60, end_date=None):
        self.root = Path(root)
        self.feed = feed
        self.sessions = sessions
        self.end_date = end_date

    def run(self):
        return {
            "run_id": "synthetic_no_cost",
            "feed": self.feed.upper(),
            "sessions": self.sessions,
            "start_date": "2026-08-28",
            "end_date": "2026-08-28",
            "candidate_contexts": _context(),
            "minute_files": [],
            "output_dir": str(self.root / "data" / "research" / "multistrategy" / "synthetic_no_cost"),
        }


def _blocked_http(*args, **kwargs):
    raise AssertionError("API-free smoke test attempted an HTTP request")


def test_api_free_runner_executes_real_orb_replay_and_writes_artifacts(tmp_path, monkeypatch):
    cache = tmp_path / "data" / "cache" / "multistrategy_alpaca" / "minute"
    cache.mkdir(parents=True)
    _minute_bars().to_csv(cache / "2026-08-28_sip.csv.gz", index=False, compression="gzip")

    monkeypatch.setattr(runner, "MultiStrategyStudy", _FakeStudy)
    monkeypatch.setattr("requests.sessions.Session.request", _blocked_http)

    result = runner.run_research(
        root=tmp_path,
        feed="sip",
        sessions=1,
        end_date="2026-08-28",
        strategies=("orb",),
        min_n=1,
    )

    assert not result.signals.empty
    assert set(result.signals["strategy_id"]) == {"ORB"}
    assert "ORB_LONG_BREAK" in set(result.signals["variant_id"])
    assert set(result.signals["split"]) == {"validation"}

    assert not result.replays.empty
    assert set(result.replays["slippage_bps"]) == {10.0, 25.0, 50.0, 75.0, 100.0}
    assert result.replays["entry_timestamp"].min() > result.signals["signal_timestamp"].min()
    assert not result.summary.empty
    assert not result.leaderboard.empty
    assert not result.best_hold_times.empty

    expected = {
        "signals.csv",
        "replay_grid.csv.gz",
        "strategy_summary.csv",
        "market_cap_summary.csv",
        "leaderboard.csv",
        "slippage_summary.csv",
        "peak_timing.csv",
        "best_hold_times.csv",
        "skips.csv",
        "run_meta.json",
        "news.md",
    }
    assert expected.issubset({path.name for path in result.output_dir.iterdir()})

    latest = tmp_path / "data" / "latest"
    assert (latest / "multistrategy_leaderboard.csv").exists()
    assert (latest / "multistrategy_best_hold_times.csv").exists()
    assert (latest / "multistrategy_peak_timing.csv").exists()
    assert (latest / "multistrategy_signals.csv").exists()
    assert "ORB" in (latest / "multistrategy_news.md").read_text(encoding="utf-8")
