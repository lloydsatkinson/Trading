import pandas as pd

from scripts.run_fixed_stop_replay import select_frozen_candidates


def test_frozen_candidates_include_extreme_pop_and_drop_only():
    trades = pd.DataFrame([
        {
            "strategy": "SSR_FLUSH_RECLAIM", "side": "LONG", "ticker": "SSR", "session_date": "2026-07-01",
            "signal_ts": "2026-07-01T15:00:00Z", "entry_ts": "2026-07-01T15:01:00Z", "entry": 10.0, "stop": 9.6,
        },
        {
            "strategy": "FAILED_HOD_BREAK", "side": "SHORT", "ticker": "HOD", "session_date": "2026-07-01",
            "signal_ts": "2026-07-01T15:30:00Z", "entry_ts": "2026-07-01T15:31:00Z", "entry": 14.0, "stop": 14.7,
        },
        {
            "strategy": "POP_AND_DROP", "side": "SHORT", "ticker": "POP", "session_date": "2026-07-01",
            "signal_ts": "2026-07-01T14:00:00Z", "entry_ts": "2026-07-01T14:01:00Z", "entry": 18.0, "stop": 19.5,
        },
        {
            "strategy": "POP_AND_DROP", "side": "SHORT", "ticker": "LOW", "session_date": "2026-07-01",
            "signal_ts": "2026-07-01T14:00:00Z", "entry_ts": "2026-07-01T14:01:00Z", "entry": 16.0, "stop": 17.0,
        },
    ])
    coarse = pd.DataFrame([
        {"date": "2026-07-01", "ticker": "SSR", "previous_close": 10.0},
        {"date": "2026-07-01", "ticker": "HOD", "previous_close": 10.5},
        {"date": "2026-07-01", "ticker": "POP", "previous_close": 10.0},
        {"date": "2026-07-01", "ticker": "LOW", "previous_close": 10.0},
    ])

    out = select_frozen_candidates(trades, coarse)

    assert set(out["candidate"]) == {
        "SSR_FLUSH_RECLAIM_RISK_3_5",
        "FAILED_HOD_BREAK_30_50_MIDDAY",
        "POP_AND_DROP_EXTREME_75_PLUS",
    }
    assert set(out.loc[out["candidate"].eq("POP_AND_DROP_EXTREME_75_PLUS"), "ticker"]) == {"POP"}
