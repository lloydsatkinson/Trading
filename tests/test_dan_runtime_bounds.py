import pandas as pd

from scanner.core.multisession_replay import SwingReplayRule
from scanner.strategies.dan_irish.research import replay_dan_swing_signals


def _daily(symbol="AAA", periods=15):
    sessions = pd.bdate_range("2026-08-03", periods=periods)
    bars = pd.DataFrame([
        {
            "symbol": symbol,
            "timestamp": pd.Timestamp(f"{day.date()} 16:00", tz="America/New_York").tz_convert("UTC"),
            "open": 5.0,
            "high": 5.2,
            "low": 4.9,
            "close": 5.0,
            "volume": 1000,
            "vwap": 5.0,
        }
        for day in sessions
    ])
    return sessions, bars


def test_swing_replay_loads_only_entry_plus_maximum_hold_sessions(tmp_path, monkeypatch):
    sessions, daily = _daily()
    calls = []

    def minute_loader(root, namespace, day, feed, symbol):
        calls.append(str(day))
        return pd.DataFrame([{
            "symbol": symbol,
            "timestamp": pd.Timestamp(f"{day} 09:30", tz="America/New_York").tz_convert("UTC"),
            "open": 5.0,
            "high": 5.05,
            "low": 4.95,
            "close": 5.0,
            "volume": 100,
            "vwap": 5.0,
        }])

    monkeypatch.setattr(
        "scanner.strategies.dan_irish.research.default_dan_swing_rules",
        lambda signal: [SwingReplayRule(stop_pct=0.08, target_r_multiple=2.0, max_hold_sessions=10)],
    )

    signals = pd.DataFrame([{
        "strategy_id": "DAN_IRISH",
        "variant_id": "DAN_OVERNIGHT_NEXT_OPEN",
        "setup_id": "OVERNIGHT_NEXT_OPEN",
        "symbol": "AAA",
        "date": str(sessions[0].date()),
        "direction": "LONG",
        "split": "validation",
        "entry_timestamp": pd.Timestamp(
            f"{sessions[0].date()} 09:30", tz="America/New_York"
        ),
        "entry_price_raw": 5.0,
        "stop_reference": 4.6,
    }])

    replays, skips = replay_dan_swing_signals(
        tmp_path,
        "sip",
        signals,
        daily,
        {"validation": str(sessions[-1].date())},
        minute_loader,
        slippage_bps=(25.0,),
    )

    assert skips.empty
    assert not replays.empty
    expected = [str(day.date()) for day in sessions[:11]]
    assert calls == expected
