import pandas as pd

import scripts.run_strategy_research as runner
from scanner.multistrategy.config import MultiStrategyConfig
from scanner.portfolio.strategy_ranker import rank_strategies


def _row(setup_id, pf, expectancy):
    return {
        "strategy_id": "DAN_IRISH",
        "variant_id": "DAN_DAY2_CONTINUATION",
        "setup_id": setup_id,
        "direction": "LONG",
        "rule_id": "S08_R2_HS2",
        "split": "validation",
        "slippage_bps": 25.0,
        "n": 30,
        "profit_factor": pf,
        "expectancy": expectancy,
        "median_return": 0.02,
        "max_drawdown": -0.15,
        "max_hold_sessions": 2,
        "stop_pct": 0.08,
        "target_r_multiple": 2.0,
    }


def test_existing_multistrategy_price_gate_remains_1_to_30():
    cfg = MultiStrategyConfig()
    assert cfg.min_price == 1.0
    assert cfg.max_price == 30.0


def test_serclick_historical_lock_date_is_unchanged():
    assert runner.SERCLICK_BASELINE_END.isoformat() == "2026-08-27"


def test_dan_uses_current_five_percent_production_expectancy_hurdle():
    summary = pd.DataFrame([
        _row("BELOW", 1.8, 0.049),
        _row("MEETS", 1.8, 0.050),
    ])
    ranked = rank_strategies(summary, min_n=20)
    eligibility = dict(zip(ranked["setup_id"], ranked["production_eligible"]))
    assert eligibility == {"BELOW": False, "MEETS": True}
    assert ranked["production_min_expectancy"].eq(0.05).all()


def test_ranker_keeps_distinct_dan_setup_ids_separate():
    summary = pd.DataFrame([
        _row("RET65_BASE1", 1.8, 0.060),
        _row("RET80_BASE1", 1.4, 0.055),
    ])
    ranked = rank_strategies(summary, min_n=20)
    assert len(ranked) == 2
    assert set(ranked["setup_id"]) == {"RET65_BASE1", "RET80_BASE1"}
    assert set(ranked["max_hold_sessions"]) == {2}
