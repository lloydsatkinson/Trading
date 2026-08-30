import pandas as pd

from scanner.portfolio.strategy_ranker import rank_strategies


def _row(strategy, rule, split, pf, exp, n=30, median=0.01, dd=-0.10, slip=25):
    return {
        "strategy_id": strategy,
        "variant_id": strategy + "_V",
        "direction": "LONG",
        "rule_id": rule,
        "split": split,
        "slippage_bps": slip,
        "n": n,
        "profit_factor": pf,
        "expectancy": exp,
        "median_return": median,
        "max_drawdown": dd,
    }


def test_ranker_ignores_forward_when_selecting_rule():
    summary = pd.DataFrame([
        _row("ORB", "VALIDATION_WINNER", "validation", 1.8, 0.03),
        _row("ORB", "VALIDATION_WINNER", "forward", 0.8, -0.02),
        _row("ORB", "FORWARD_MIRAGE", "validation", 1.1, 0.005),
        _row("ORB", "FORWARD_MIRAGE", "forward", 99.0, 0.50),
    ])
    ranked = rank_strategies(summary, min_n=20)
    assert ranked.iloc[0]["rule_id"] == "VALIDATION_WINNER"


def test_ranker_prefers_validation_rows_at_baseline_25bps():
    summary = pd.DataFrame([
        _row("VWAP", "ROBUST", "validation", 1.7, 0.025, slip=25),
        _row("VWAP", "ROBUST", "validation", 0.9, -0.01, slip=100),
        _row("VWAP", "OPTIMISTIC_ONLY", "validation", 2.5, 0.06, slip=10),
        _row("VWAP", "OPTIMISTIC_ONLY", "validation", 1.2, 0.005, slip=25),
    ])
    ranked = rank_strategies(summary, min_n=20, baseline_slippage_bps=25)
    assert ranked.iloc[0]["rule_id"] == "ROBUST"


def test_ranker_excludes_small_samples_by_default():
    summary = pd.DataFrame([
        _row("ORB", "TINY", "validation", 8.0, 0.20, n=4),
        _row("ORB", "ENOUGH", "validation", 1.5, 0.02, n=25),
    ])
    ranked = rank_strategies(summary, min_n=20)
    assert ranked["rule_id"].tolist() == ["ENOUGH"]


def test_ranker_keeps_test_and_forward_as_reporting_only_columns():
    summary = pd.DataFrame([
        _row("SERCLICK_LEO", "A", "validation", 1.6, 0.02),
        _row("SERCLICK_LEO", "A", "test", 1.4, 0.015),
        _row("SERCLICK_LEO", "A", "forward", 1.3, 0.01),
    ])
    ranked = rank_strategies(summary, min_n=20)
    row = ranked.iloc[0]
    assert row["validation_profit_factor"] == 1.6
    assert row["test_profit_factor"] == 1.4
    assert row["forward_profit_factor"] == 1.3


def test_ranker_carries_selected_rule_metadata():
    row = _row("ORB", "A", "validation", 1.6, 0.02)
    row.update({"max_hold_minutes": 60, "stop_pct": 0.05, "target_pct": 0.10, "hold_to_eod": False})
    ranked = rank_strategies(pd.DataFrame([row]), min_n=20)
    assert ranked.iloc[0]["max_hold_minutes"] == 60
    assert ranked.iloc[0]["stop_pct"] == 0.05
    assert ranked.iloc[0]["target_pct"] == 0.10
