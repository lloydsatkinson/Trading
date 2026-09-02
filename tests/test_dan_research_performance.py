from datetime import date

import pandas as pd

import scanner.strategies.dan_irish.research as research
from scanner.strategies.dan_irish.config import DanConfig


def _daily_fixture():
    rows = []
    for symbol in ("AAA", "BBB"):
        for day in pd.bdate_range("2026-08-28", periods=5):
            rows.append({
                "symbol": symbol,
                "timestamp": pd.Timestamp(f"{day.date()} 16:00", tz="America/New_York").tz_convert("UTC"),
                "open": 5.0,
                "high": 5.2,
                "low": 4.8,
                "close": 5.0,
                "volume": 1000,
                "vwap": 5.0,
            })
    return pd.DataFrame(rows)


class _Study:
    def __init__(self):
        self.calls = []

    def ensure_minute_day(self, symbols, day):
        self.calls.append((tuple(symbols), day))
        return pd.DataFrame()


def test_followup_cache_planning_prepares_daily_bars_once(monkeypatch):
    calls = 0
    original = research.prepare_intraday_bars

    def counted(frame):
        nonlocal calls
        calls += 1
        return original(frame)

    monkeypatch.setattr(research, "prepare_intraday_bars", counted)
    contexts = pd.DataFrame([
        {"symbol": "AAA", "date": "2026-08-28"},
        {"symbol": "AAA", "date": "2026-08-31"},
        {"symbol": "BBB", "date": "2026-08-28"},
    ])
    study = _Study()

    research.ensure_dan_followup_caches(
        study,
        contexts,
        _daily_fixture(),
        DanConfig(followup_sessions=2),
    )

    assert calls == 1
    assert study.calls


def test_bounded_symbol_loader_reads_each_day_once_and_returns_isolated_copies(tmp_path):
    calls = []

    def day_loader(root, namespace, day, feed):
        calls.append((str(root), namespace, day, feed))
        return pd.DataFrame([
            {"symbol": "AAA", "close": 5.0},
            {"symbol": "BBB", "close": 7.0},
        ])

    loader = research.make_cached_symbol_minute_loader(day_loader, max_days=2)

    first = loader(tmp_path, "ns", "2026-08-28", "sip", "AAA")
    second_symbol = loader(tmp_path, "ns", "2026-08-28", "sip", "BBB")
    first.loc[first.index[0], "close"] = 999.0
    first_again = loader(tmp_path, "ns", "2026-08-28", "sip", "AAA")

    assert len(calls) == 1
    assert first_again.iloc[0]["close"] == 5.0
    assert second_symbol.iloc[0]["close"] == 7.0

    loader(tmp_path, "ns", "2026-08-29", "sip", "AAA")
    loader(tmp_path, "ns", "2026-08-30", "sip", "AAA")
    loader(tmp_path, "ns", "2026-08-28", "sip", "AAA")
    assert len(calls) == 4
