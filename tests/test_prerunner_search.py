import pandas as pd

from trading_lab.prerunner import build_snapshots
from trading_lab.prerunner_search import (
    assign_chronological_splits,
    discover_rules,
    feature_lift_table,
)

NY = "America/New_York"


def test_sparse_snapshot_signal_time_is_freeze_not_last_print():
    bars = pd.DataFrame([
        {"timestamp": pd.Timestamp("2026-08-10 09:20", tz=NY).tz_convert("UTC"), "ticker": "X", "open": 2.0, "high": 2.0, "low": 2.0, "close": 2.0, "volume": 100, "previous_close": 1.8},
        {"timestamp": pd.Timestamp("2026-08-10 09:30", tz=NY).tz_convert("UTC"), "ticker": "X", "open": 2.1, "high": 2.2, "low": 2.0, "close": 2.1, "volume": 100, "previous_close": 1.8},
    ])
    snap = build_snapshots(bars, freeze_times=("09:25",)).iloc[0]
    ts = pd.Timestamp(snap.signal_ts).tz_convert(NY)
    assert ts.strftime("%H:%M") == "09:25"


def test_feature_lift_thresholds_are_development_only():
    frame = pd.DataFrame({
        "session_date": ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05", "2026-01-06"],
        "freeze_time": ["09:31"] * 6,
        "split": ["development"] * 4 + ["validation"] * 2,
        "open_rvol": [1.0, 2.0, 3.0, 4.0, 100.0, 1000.0],
        "long_reach_20": [False, False, True, True, True, True],
        "short_reach_20": [False] * 6,
    })
    lift = feature_lift_table(
        frame,
        side="LONG",
        target_pct=20,
        features=("open_rvol",),
        quantiles=(0.5,),
        min_signals=1,
    )
    assert set(lift.threshold.round(6)) == {2.5}


def test_discovered_rule_clauses_never_use_outcome_columns():
    rows = []
    for i in range(40):
        rows.append({
            "session_date": f"2026-01-{1 + i % 20:02d}",
            "freeze_time": "09:31",
            "split": "development",
            "open_rvol": float(i + 1),
            "gain_retention": float(i) / 40,
            "long_reach_20": bool(i >= 20),
            "short_reach_20": bool(i < 10),
        })
    frame = pd.DataFrame(rows)
    rules = discover_rules(
        frame,
        side="LONG",
        target_pct=20,
        features=("open_rvol", "gain_retention"),
        min_signals=5,
        top_single=6,
        max_pairs=6,
    )
    assert rules
    for rule in rules:
        assert rule.side == "LONG"
        assert all(c.feature in {"open_rvol", "gain_retention"} for c in rule.clauses)


def test_chronological_split_is_60_20_20_and_ordered():
    dates = [f"2026-01-{d:02d}" for d in range(1, 11)]
    frame = pd.DataFrame({"session_date": dates})
    out = assign_chronological_splits(frame)
    assert out.split.tolist() == ["development"] * 6 + ["validation"] * 2 + ["test"] * 2
