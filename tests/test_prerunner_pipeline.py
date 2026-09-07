import pandas as pd

from trading_lab.prerunner import ExecutionRule
from trading_lab.prerunner_pipeline import (
    assemble_labeled_snapshots,
    replay_rule,
)
from trading_lab.prerunner_search import Clause, SnapshotRule

NY = "America/New_York"


def _bar(day, time, o, h, l, c, v=1000, ticker="AAA", previous_close=2.0):
    return {
        "session_date": day,
        "date": day,
        "ticker": ticker,
        "timestamp": pd.Timestamp(f"{day} {time}", tz=NY).tz_convert("UTC"),
        "open": o,
        "high": h,
        "low": l,
        "close": c,
        "volume": v,
        "previous_close": previous_close,
    }


def test_assemble_labeled_snapshots_uses_future_only_for_labels():
    day = "2026-08-10"
    minute = pd.DataFrame([
        _bar(day, "09:20", 2.00, 2.02, 1.99, 2.01),
        _bar(day, "09:30", 2.01, 2.08, 2.00, 2.06, 5000),
        _bar(day, "09:31", 2.06, 2.10, 2.05, 2.08, 5000),
        _bar(day, "09:32", 2.08, 2.30, 2.00, 2.20, 5000),
        _bar(day, "09:33", 2.20, 3.00, 1.50, 2.50, 5000),
    ])
    history = pd.DataFrame([
        _bar("2026-08-06", "09:30", 2, 2, 2, 2, 2500),
        _bar("2026-08-06", "09:31", 2, 2, 2, 2, 2500),
        _bar("2026-08-07", "09:30", 2, 2, 2, 2, 2500),
        _bar("2026-08-07", "09:31", 2, 2, 2, 2, 2500),
    ])
    manifest = pd.DataFrame([{
        "session_date": day,
        "ticker": "AAA",
        "selection_role": "signal_active",
        "prior20_median_volume": 400_000,
        "prior20_max_volume": 900_000,
        "prior4d_return": 0.10,
    }])
    out = assemble_labeled_snapshots(minute, history, manifest, freeze_times=("09:31",))
    assert len(out) == 1
    row = out.iloc[0]
    assert row.signal_ts.endswith("13:31:00+00:00")
    assert row.selection_role == "signal_active"
    assert row.prior20_median_volume == 400_000
    assert bool(row.long_reach_20)
    assert bool(row.short_reach_20)
    assert row.open_rvol == 2.0


def _two_day_replay_inputs():
    snapshots = pd.DataFrame([
        {
            "session_date": "2026-08-10", "ticker": "AAA", "freeze_time": "09:31",
            "signal_ts": pd.Timestamp("2026-08-10 09:31", tz=NY).tz_convert("UTC").isoformat(),
            "open_rvol": 3.0, "split": "development",
        },
        {
            "session_date": "2026-08-11", "ticker": "AAA", "freeze_time": "09:31",
            "signal_ts": pd.Timestamp("2026-08-11 09:31", tz=NY).tz_convert("UTC").isoformat(),
            "open_rvol": 4.0, "split": "validation",
        },
    ])
    minute = pd.DataFrame([
        _bar("2026-08-10", "09:31", 2.0, 2.0, 2.0, 2.0),
        _bar("2026-08-10", "09:32", 2.0, 2.3, 1.99, 2.2),
        _bar("2026-08-11", "09:31", 2.0, 2.0, 2.0, 2.0),
        _bar("2026-08-11", "09:32", 2.0, 1.95, 1.6, 1.7),
    ])
    return snapshots, minute


def test_replay_rule_respects_split_and_side():
    snapshots, minute = _two_day_replay_inputs()
    rule = SnapshotRule("L1", "LONG", "09:31", (Clause("open_rvol", ">=", 2.0),))
    execution = ExecutionRule(stop_pct=0.05, target_pct=0.10, max_hold_minutes=10, slippage_bps=0)
    dev = replay_rule(snapshots, minute, rule, execution, split="development")
    val = replay_rule(snapshots, minute, rule, execution, split="validation")
    assert len(dev) == 1 and dev.iloc[0].session_date == "2026-08-10"
    assert dev.iloc[0].side == "LONG"
    assert dev.iloc[0].return_r == 2.0
    assert len(val) == 1 and val.iloc[0].session_date == "2026-08-11"
    assert val.iloc[0].return_r == -1.0
