import pandas as pd

from trading_lab.fixed_stop import simulate_fixed_stop


def test_fixed_stop_changes_only_stop_and_preserves_long_target():
    bars = pd.DataFrame([
        {"timestamp":"2026-07-01T14:31:00Z","open":10.0,"high":10.4,"low":9.7,"close":10.2},
        {"timestamp":"2026-07-01T14:32:00Z","open":10.2,"high":11.1,"low":10.0,"close":10.9},
    ])
    r = simulate_fixed_stop(bars, side="LONG", entry=10.0, target=11.0, stop_pct=0.50, slip_bps=0)
    assert r["stop"] == 5.0
    assert r["target"] == 11.0
    assert r["reason"] == "TARGET"
    assert r["exit"] == 11.0
    assert r["return_pct"] == 0.10


def test_fixed_stop_changes_only_stop_and_preserves_short_target():
    bars = pd.DataFrame([
        {"timestamp":"2026-07-01T14:31:00Z","open":10.0,"high":10.4,"low":9.8,"close":9.9},
        {"timestamp":"2026-07-01T14:32:00Z","open":9.9,"high":10.0,"low":8.9,"close":9.0},
    ])
    r = simulate_fixed_stop(bars, side="SHORT", entry=10.0, target=9.0, stop_pct=0.50, slip_bps=0)
    assert r["stop"] == 15.0
    assert r["target"] == 9.0
    assert r["reason"] == "TARGET"
    assert r["exit"] == 9.0
    assert r["return_pct"] == 0.10
