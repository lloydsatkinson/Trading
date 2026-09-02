import pandas as pd

import scripts.run_strategy_research as runner
from scanner.core.replay import ReplayRule


def _bars():
    return pd.DataFrame([
        {
            "symbol": "AAA",
            "timestamp": pd.Timestamp("2026-08-28 10:00", tz="America/New_York").tz_convert("UTC"),
            "open": 5.00,
            "high": 5.10,
            "low": 4.95,
            "close": 5.05,
            "volume": 1000,
            "vwap": 5.02,
        },
        {
            "symbol": "AAA",
            "timestamp": pd.Timestamp("2026-08-28 10:01", tz="America/New_York").tz_convert("UTC"),
            "open": 5.05,
            "high": 5.20,
            "low": 5.00,
            "close": 5.15,
            "volume": 1200,
            "vwap": 5.08,
        },
    ])


def _signals():
    common = {
        "strategy_id": "DAN_IRISH",
        "variant_id": "DAN_INTRADAY_SECONDARY",
        "symbol": "AAA",
        "date": "2026-08-28",
        "entry_timestamp": pd.Timestamp("2026-08-28 10:00", tz="America/New_York").tz_convert("UTC"),
        "entry_price_raw": 5.00,
        "direction": "LONG",
        "stop_reference": 4.80,
        "split": "validation",
        "_cache_namespace": "multistrategy_alpaca",
    }
    return pd.DataFrame([
        {**common, "setup_id": "C10_BASE_HIGH_V1P0", "min_consolidation_minutes": 10},
        {**common, "setup_id": "C20_BASE_HIGH_V1P0", "min_consolidation_minutes": 20},
    ])


def test_identical_dan_physical_entry_replays_once_and_fans_out_setup_ids(monkeypatch, tmp_path):
    replay_calls = []

    monkeypatch.setattr(runner, "_load_minute_bars", lambda *args, **kwargs: _bars())
    monkeypatch.setattr(
        runner,
        "default_rules_for_signal",
        lambda signal, serclick=False: [ReplayRule(stop_pct=0.10, target_pct=0.20, max_hold_minutes=5)],
    )
    monkeypatch.setattr(
        runner,
        "analyze_same_session_peak",
        lambda *args, **kwargs: pd.Series({"peak_return_pct": 0.12, "minutes_to_peak": 1.0}),
    )

    def fake_replay(symbol_bars, priced, rules, session_end="16:00"):
        replay_calls.append(str(priced["setup_id"]))
        return pd.DataFrame([{
            **priced,
            "exit_reason": "TIME",
            "exit_timestamp": priced["entry_timestamp"],
            "exit_price": float(priced["entry_price_slipped"]),
            "return_pct": 0.0,
            "bars_held": 1,
            "mfe_pct": 0.0,
            "mae_pct": 0.0,
            "r_multiple": 0.0,
        }])

    monkeypatch.setattr(runner, "replay_signal_grid", fake_replay)

    out, skips = runner.replay_signals(tmp_path, "sip", _signals(), slippage_bps=(25,))

    assert skips.empty
    assert len(replay_calls) == 1
    assert set(out["setup_id"].astype(str)) == {
        "C10_BASE_HIGH_V1P0",
        "C20_BASE_HIGH_V1P0",
    }
    assert len(out) == 2
