from pathlib import Path

import pandas as pd
import pytest

import scripts.run_strategy_research as runner


def _bars(rows):
    return pd.DataFrame([
        {
            "symbol": "AAA",
            "timestamp": pd.Timestamp(ts, tz="America/New_York").tz_convert("UTC"),
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "vwap": vwap,
        }
        for ts, open_, high, low, close, volume, vwap in rows
    ])


def _long_bars():
    return _bars([
        ("2026-08-28 09:30", 4.50, 4.55, 4.45, 4.52, 100, 4.50),
        ("2026-08-28 09:31", 4.60, 4.80, 4.58, 4.75, 100, 4.72),
        ("2026-08-28 09:32", 4.74, 4.76, 4.50, 4.55, 100, 4.56),
        ("2026-08-28 09:33", 4.56, 4.75, 4.54, 4.72, 300, 4.69),
        ("2026-08-28 09:34", 4.73, 4.90, 4.70, 4.85, 200, 4.82),
    ])


def _short_bars():
    return _bars([
        ("2026-08-28 09:30", 4.50, 4.55, 4.45, 4.52, 100, 4.50),
        ("2026-08-28 09:31", 4.60, 4.90, 4.58, 4.85, 100, 4.82),
        ("2026-08-28 09:32", 4.84, 4.86, 4.50, 4.55, 120, 4.58),
        ("2026-08-28 09:33", 4.56, 4.72, 4.50, 4.58, 150, 4.62),
        ("2026-08-28 09:34", 4.57, 4.60, 4.38, 4.42, 350, 4.48),
        ("2026-08-28 09:35", 4.40, 4.45, 4.25, 4.30, 220, 4.34),
    ])


def _context():
    return pd.DataFrame([{
        "symbol": "AAA",
        "date": "2026-08-28",
        "split": "validation",
        "feed": "SIP",
        "prior_close": 4.0,
        "market_cap": 200_000_000.0,
        "market_cap_bucket": "MICROCAP",
        "pm_gap_pct": 0.15,
        "pm_dollar_turnover": 5_000_000.0,
        "opening_rvol": 6.0,
        "float_shares": 12_000_000.0,
        "catalyst_class": "NEWS",
    }])


def _fake_study(context):
    class FakeStudy:
        def __init__(self, root=".", feed="sip", sessions=60, end_date=None):
            self.root = Path(root)
            self.feed = feed
            self.sessions = sessions

        def run(self):
            return {
                "run_id": "synthetic_vwap_no_cost",
                "feed": self.feed.upper(),
                "sessions": self.sessions,
                "start_date": "2026-08-28",
                "end_date": "2026-08-28",
                "candidate_contexts": context.copy(),
                "minute_files": [],
                "output_dir": str(self.root / "data" / "research" / "multistrategy" / "synthetic_vwap_no_cost"),
            }

    return FakeStudy


def _blocked_http(*args, **kwargs):
    raise AssertionError("VWAP API-free smoke test attempted an HTTP request")


def _run(tmp_path, monkeypatch, bars):
    cache = tmp_path / "data" / "cache" / "multistrategy_alpaca" / "minute"
    cache.mkdir(parents=True)
    bars.to_csv(cache / "2026-08-28_sip.csv.gz", index=False, compression="gzip")
    monkeypatch.setattr(runner, "MultiStrategyStudy", _fake_study(_context()))
    monkeypatch.setattr("requests.sessions.Session.request", _blocked_http)
    return runner.run_research(
        root=tmp_path,
        feed="sip",
        sessions=1,
        end_date="2026-08-28",
        strategies=("vwap",),
        min_n=1,
    )


@pytest.mark.parametrize(
    ("fixture", "variant", "direction"),
    [
        (_long_bars, "VWAP_LONG_RECLAIM", "LONG"),
        (_short_bars, "VWAP_SHORT_REJECTION", "SHORT"),
    ],
)
def test_api_free_vwap_runner_exercises_real_long_and_short_paths(tmp_path, monkeypatch, fixture, variant, direction):
    result = _run(tmp_path, monkeypatch, fixture())

    selected = result.signals[result.signals["variant_id"].eq(variant)]
    assert not selected.empty
    assert set(selected["direction"]) == {direction}
    assert set(selected["split"]) == {"validation"}

    replay = result.replays[result.replays["variant_id"].eq(variant)]
    assert not replay.empty
    assert set(replay["slippage_bps"]) == {10.0, 25.0, 50.0, 75.0, 100.0}
    assert replay["entry_timestamp"].min() > selected["signal_timestamp"].min()
    assert not result.summary[result.summary["variant_id"].eq(variant)].empty
