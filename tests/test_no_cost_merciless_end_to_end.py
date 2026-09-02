from pathlib import Path

import pandas as pd

import scripts.run_strategy_research as runner
from scanner.core.replay import ReplayRule


def _minute_bars() -> pd.DataFrame:
    rows = [
        ("09:30", 4.45, 4.58, 4.42, 4.54, 120),
        ("09:31", 4.54, 4.92, 4.52, 4.88, 360),
        ("09:32", 4.86, 4.94, 4.78, 4.90, 150),
        ("09:33", 4.88, 4.93, 4.80, 4.89, 120),
        ("09:34", 4.87, 4.94, 4.82, 4.91, 110),
        ("09:35", 4.91, 5.02, 4.90, 5.00, 300),
        ("09:36", 5.01, 5.12, 4.99, 5.08, 210),
        ("09:37", 5.08, 5.10, 4.95, 4.99, 130),
        ("09:38", 4.99, 5.04, 4.94, 5.01, 100),
        ("09:39", 5.01, 5.07, 4.98, 5.05, 90),
        ("09:40", 5.05, 5.18, 5.04, 5.16, 320),
        ("09:41", 5.17, 5.28, 5.14, 5.24, 220),
        ("09:42", 5.23, 5.25, 5.10, 5.14, 120),
        ("09:43", 5.14, 5.19, 5.09, 5.16, 100),
        ("09:44", 5.16, 5.22, 5.12, 5.20, 90),
        ("09:45", 5.20, 5.34, 5.19, 5.32, 310),
        ("09:46", 5.33, 5.45, 5.30, 5.41, 210),
        ("09:47", 5.41, 5.55, 5.38, 5.50, 180),
        ("09:48", 5.50, 5.62, 5.46, 5.58, 170),
        ("09:49", 5.58, 5.64, 5.48, 5.52, 150),
        ("09:50", 5.52, 5.60, 5.44, 5.55, 140),
        ("09:51", 5.55, 5.68, 5.52, 5.66, 230),
        ("09:52", 5.66, 5.74, 5.60, 5.70, 180),
        ("09:53", 5.70, 5.76, 5.62, 5.68, 170),
        ("09:54", 5.68, 5.72, 5.60, 5.64, 160),
        ("09:55", 5.64, 5.70, 5.58, 5.66, 150),
        ("09:56", 5.66, 5.73, 5.62, 5.71, 160),
        ("09:57", 5.71, 5.80, 5.68, 5.78, 180),
        ("09:58", 5.78, 5.86, 5.74, 5.84, 170),
        ("09:59", 5.84, 5.90, 5.80, 5.88, 160),
        ("10:00", 5.88, 5.94, 5.84, 5.90, 150),
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
        "pm_gap_pct": 0.15,
        "pm_dollar_turnover": 5_000_000.0,
        "opening_rvol": 6.0,
        "market_cap": 200_000_000.0,
        "market_cap_bucket": "MICROCAP",
        "float_shares": 12_000_000.0,
        "catalyst_class": "NEWS",
    }])


class _FakeStudy:
    def __init__(self, root=".", feed="sip", sessions=60, end_date=None):
        self.root = Path(root)
        self.feed = feed
        self.sessions = sessions
        self.end_date = end_date

    def run(self):
        return {
            "run_id": "synthetic_merciless",
            "feed": self.feed.upper(),
            "sessions": self.sessions,
            "start_date": "2026-08-28",
            "end_date": "2026-08-28",
            "candidate_contexts": _context(),
            "minute_files": [],
            "output_dir": str(self.root / "data" / "research" / "multistrategy" / "synthetic_merciless"),
        }


def _blocked_http(*args, **kwargs):
    raise AssertionError("API-free Merciless smoke test attempted an HTTP request")


def _single_structural_rule(signal, serclick=False):
    return [
        ReplayRule(
            stop_price=float(signal["stop_reference"]),
            target_r_multiple=1.0,
            max_hold_minutes=5,
        )
    ]


def test_api_free_runner_executes_merciless_and_writes_edge_artifacts(tmp_path, monkeypatch):
    cache = tmp_path / "data" / "cache" / "multistrategy_alpaca" / "minute"
    cache.mkdir(parents=True)
    _minute_bars().to_csv(cache / "2026-08-28_sip.csv.gz", index=False, compression="gzip")

    monkeypatch.setattr(runner, "MultiStrategyStudy", _FakeStudy)
    monkeypatch.setattr(runner, "default_rules_for_signal", _single_structural_rule)
    monkeypatch.setattr("requests.sessions.Session.request", _blocked_http)

    result = runner.run_research(
        root=tmp_path,
        feed="sip",
        sessions=1,
        end_date="2026-08-28",
        strategies=("merciless",),
        min_n=1,
    )

    assert not result.signals.empty
    assert set(result.signals["strategy_id"]) == {"MERCILESS_Q"}
    assert result.signals["sequence_number"].min() == 1
    assert not result.replays.empty
    assert set(result.replays["slippage_bps"]) == {10.0, 25.0, 50.0, 75.0, 100.0}
    assert not result.sequence_edge.empty
    assert not result.friction_break_even.empty
    assert not result.sequence_summary.empty
    assert not result.friction_thresholds.empty

    assert (result.output_dir / "merciless_sequence_edge.csv").exists()
    assert (result.output_dir / "merciless_friction_break_even.csv").exists()
    assert (result.output_dir / "merciless_sequence_summary.csv").exists()
    assert (result.output_dir / "merciless_friction_summary.csv").exists()
    latest = tmp_path / "data" / "latest"
    assert (latest / "merciless_sequence_edge.csv").exists()
    assert (latest / "merciless_friction_break_even.csv").exists()
    assert (latest / "merciless_sequence_summary.csv").exists()
    assert (latest / "merciless_friction_summary.csv").exists()
    news = (latest / "multistrategy_news.md").read_text(encoding="utf-8")
    assert "MERCILESS_Q" in news
    assert "Merciless repeat-entry edge" in news
    assert "Merciless friction resilience" in news


def test_strategy_parser_accepts_merciless_and_all_includes_it():
    assert runner._parse_strategies("merciless") == ("merciless",)
    assert "merciless" in runner._parse_strategies("all")
