import pandas as pd

from trading_lab.prerunner_optimizer import (
    development_thresholds,
    pareto_frontier,
    performance_metrics,
)


def test_threshold_discovery_ignores_non_development_extremes():
    frame = pd.DataFrame({
        "split": ["development", "development", "validation", "test"],
        "open_rvol": [1.0, 3.0, 100.0, 10_000.0],
    })
    q = development_thresholds(frame, ["open_rvol"], quantiles=(0.5,))
    assert len(q) == 1
    assert q.iloc[0].threshold == 2.0


def test_performance_metrics_keeps_long_and_short_separate():
    trades = pd.DataFrame({
        "side": ["LONG", "LONG", "SHORT", "SHORT", "SHORT"],
        "return_r": [2.0, -1.0, 1.0, 1.0, -1.0],
    })
    long = performance_metrics(trades, side="LONG", sessions=10)
    short = performance_metrics(trades, side="SHORT", sessions=10)
    assert long["n"] == 2
    assert long["profit_factor"] == 2.0
    assert long["trades_per_day"] == 0.2
    assert short["n"] == 3
    assert short["profit_factor"] == 2.0
    assert short["trades_per_day"] == 0.3


def test_pareto_frontier_removes_dominated_rule_but_keeps_tradeoff():
    rules = pd.DataFrame([
        {"rule_id": "A", "profit_factor": 2.0, "expectancy_r": 0.20, "trades_per_day": 0.5, "max_drawdown_r": 3.0},
        {"rule_id": "B", "profit_factor": 1.6, "expectancy_r": 0.15, "trades_per_day": 1.0, "max_drawdown_r": 2.0},
        {"rule_id": "C", "profit_factor": 1.2, "expectancy_r": 0.10, "trades_per_day": 0.2, "max_drawdown_r": 4.0},
    ])
    out = pareto_frontier(
        rules,
        maximize=("profit_factor", "expectancy_r", "trades_per_day"),
        minimize=("max_drawdown_r",),
    )
    assert set(out.rule_id) == {"A", "B"}
