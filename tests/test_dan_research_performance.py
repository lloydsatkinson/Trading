from datetime import date

import pandas as pd

import scanner.strategies.dan_irish.intraday as intraday_module
import scanner.strategies.dan_irish.research as research
import scanner.strategies.dan_irish.swing as swing_module
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


def _intraday_fixture():
    rows = []
    prices = [4.40, 4.75, 5.00, 5.20, 5.05, 4.98, 4.95, 4.96, 4.98, 5.00, 5.03, 5.08, 5.22, 5.25]
    for idx, close in enumerate(prices):
        ts = pd.Timestamp("2026-08-28 09:30", tz="America/New_York") + pd.Timedelta(minutes=idx)
        rows.append({
            "symbol": "AAA",
            "timestamp": ts.tz_convert("UTC"),
            "open": close - 0.02,
            "high": close + 0.05,
            "low": close - 0.05,
            "close": close,
            "volume": 1000 if idx < 12 else 3000,
            "vwap": close,
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


def test_signal_generation_passes_only_symbol_daily_history_to_swing(monkeypatch, tmp_path):
    contexts = pd.DataFrame([
        {"symbol": "AAA", "date": "2026-08-28", "prior_close": 4.0, "dan_candidate": True},
        {"symbol": "BBB", "date": "2026-08-28", "prior_close": 4.0, "dan_candidate": True},
    ])
    seen = []

    monkeypatch.setattr(research, "ensure_dan_followup_caches", lambda *args, **kwargs: None)
    monkeypatch.setattr(research, "generate_dan_intraday_signal_grid", lambda *args, **kwargs: pd.DataFrame())

    def fake_swing(context, daily_bars, minute_loader, cfg, session_splits=None):
        seen.append((str(context["symbol"]), set(daily_bars["symbol"].astype(str))))
        return pd.DataFrame()

    monkeypatch.setattr(research, "generate_dan_swing_signals", fake_swing)

    def minute_loader(root, namespace, day, feed, symbol):
        return pd.DataFrame([{
            "symbol": symbol,
            "timestamp": pd.Timestamp(f"{day} 09:30", tz="America/New_York").tz_convert("UTC"),
            "open": 5.0,
            "high": 5.1,
            "low": 4.9,
            "close": 5.0,
            "volume": 100,
            "vwap": 5.0,
        }])

    research.generate_dan_signal_set(
        tmp_path,
        "sip",
        _Study(),
        {
            "dan_candidate_contexts": contexts,
            "daily_bars": _daily_fixture(),
            "session_splits": {},
        },
        minute_loader,
    )

    assert seen == [("AAA", {"AAA"}), ("BBB", {"BBB"})]


def test_swing_daily_frame_reuses_prepared_symbol_frame(monkeypatch):
    prepared = research.prepare_intraday_bars(_daily_fixture())
    prepared = prepared[prepared["symbol"].astype(str).eq("AAA")].copy()

    def should_not_run(frame):
        raise AssertionError("already prepared daily bars should not be normalised again")

    monkeypatch.setattr(swing_module, "prepare_intraday_bars", should_not_run)
    out = swing_module._daily_frame(prepared, "AAA")

    assert not out.empty
    assert set(out["symbol"].astype(str)) == {"AAA"}


def test_intraday_grid_prepares_session_features_once(monkeypatch):
    regular_calls = 0
    median_calls = 0
    original_regular = intraday_module._regular_session
    original_median = intraday_module.rolling_prior_volume_median

    def counted_regular(frame):
        nonlocal regular_calls
        regular_calls += 1
        return original_regular(frame)

    def counted_median(frame, lookback):
        nonlocal median_calls
        median_calls += 1
        return original_median(frame, lookback)

    monkeypatch.setattr(intraday_module, "_regular_session", counted_regular)
    monkeypatch.setattr(intraday_module, "rolling_prior_volume_median", counted_median)

    context = {
        "symbol": "AAA",
        "date": "2026-08-28",
        "prior_close": 4.0,
        "dan_candidate": True,
        "pm_high": 5.10,
        "split": "validation",
    }
    intraday_module.generate_dan_intraday_signal_grid(
        _intraday_fixture(),
        context,
        DanConfig(min_reference_extension_pct=0.15, min_retained_gain=0.40),
        consolidation_minutes=(3, 5),
        breakout_references=("BASE_HIGH", "HOD"),
        volume_ratios=(1.0, 1.5),
    )

    assert regular_calls == 1
    assert median_calls == 1
