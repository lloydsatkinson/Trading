from scripts.run_final_holdout import FINAL_CONFIGS, final_target


def test_final_configs_are_frozen_three_strategy_rules():
    assert FINAL_CONFIGS == {
        "SSR_FLUSH_RECLAIM_FINAL": {"candidate": "SSR_FLUSH_RECLAIM_RISK_3_5", "stop_pct": 0.20, "hold_minutes": 90, "target_r": 3.0},
        "FAILED_HOD_BREAK_FINAL": {"candidate": "FAILED_HOD_BREAK_30_50_MIDDAY", "stop_pct": 0.05, "hold_minutes": 10, "target_r": 2.0},
        "POP_AND_DROP_FINAL": {"candidate": "POP_AND_DROP_EXTREME_75_PLUS", "stop_pct": 0.15, "hold_minutes": 60, "target_r": 3.0},
    }


def test_final_target_uses_original_structural_risk():
    assert final_target("LONG", 10.0, 9.5, 3.0) == 11.5
    assert final_target("SHORT", 10.0, 10.5, 2.0) == 9.0
