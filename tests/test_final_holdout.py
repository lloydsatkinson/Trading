import pandas as pd

from scripts.run_final_holdout import FINAL_CONFIGS, _simulate, final_target


def test_final_configs_are_frozen_three_strategy_rules():
    assert FINAL_CONFIGS == {
        "SSR_FLUSH_RECLAIM_FINAL": {"candidate": "SSR_FLUSH_RECLAIM_RISK_3_5", "stop_pct": 0.20, "hold_minutes": 90, "target_r": 3.0},
        "FAILED_HOD_BREAK_FINAL": {"candidate": "FAILED_HOD_BREAK_30_50_MIDDAY", "stop_pct": 0.05, "hold_minutes": 10, "target_r": 2.0},
        "POP_AND_DROP_FINAL": {"candidate": "POP_AND_DROP_EXTREME_75_PLUS", "stop_pct": 0.15, "hold_minutes": 60, "target_r": 3.0},
    }


def test_final_target_uses_original_structural_risk():
    assert final_target("LONG", 10.0, 9.5, 3.0) == 11.5
    assert final_target("SHORT", 10.0, 10.5, 2.0) == 9.0


def test_stress_slippage_reprices_entry_from_baseline_20bps():
    bars = pd.DataFrame([
        {"timestamp": "2026-08-12T14:31:00Z", "open": 10.0, "high": 10.1, "low": 9.9, "close": 10.0},
    ])
    row = pd.Series({
        "config": "SSR_FLUSH_RECLAIM_FINAL",
        "candidate": "SSR_FLUSH_RECLAIM_RISK_3_5",
        "strategy": "SSR_FLUSH_RECLAIM",
        "side": "LONG",
        "ticker": "TEST",
        "session_date": "2026-08-12",
        "entry_ts": pd.Timestamp("2026-08-12T14:31:00Z"),
        "entry": 10.02,
        "stop": 9.50,
        "fixed_stop_pct": 0.20,
        "fixed_hold_minutes": 10,
        "fixed_target_r": 3.0,
    })

    result = _simulate(row, bars, slip_bps=40.0)

    # Raw next-minute open is 10.00 because the stored tournament entry already
    # includes 20bp slippage (10.00 * 1.002 = 10.02). A true 40bp stress entry
    # must therefore be 10.04, not the inherited 10.02.
    assert result["entry"] == 10.04
