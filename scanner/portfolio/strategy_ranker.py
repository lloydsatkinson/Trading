from __future__ import annotations

import math

import numpy as np
import pandas as pd


def _num(value, default=np.nan) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return float(default)
    return out if np.isfinite(out) else float(default)


def _profit_factor_num(value, default=np.nan) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return float(default)
    if np.isnan(out) or out == -np.inf:
        return float(default)
    return out


def _clip01(value: float) -> float:
    return float(np.clip(value, 0.0, 1.0))


def _slippage_component(group: pd.DataFrame) -> tuple[float, float]:
    if "slippage_bps" not in group.columns or group.empty:
        return 0.5, np.nan
    x = group[["slippage_bps", "profit_factor"]].copy()
    x["slippage_bps"] = pd.to_numeric(x["slippage_bps"], errors="coerce")
    x["profit_factor"] = pd.to_numeric(x["profit_factor"], errors="coerce")
    x = x.dropna().sort_values("slippage_bps")
    if x.empty:
        return 0.5, np.nan
    max_tested = float(x["slippage_bps"].max())
    resilient = x[x["profit_factor"] >= 1.0]
    last_profitable = float(resilient["slippage_bps"].max()) if not resilient.empty else 0.0
    return (_clip01(last_profitable / max_tested) if max_tested > 0 else 0.5), last_profitable


def _split_metric(summary: pd.DataFrame, split: str, key: tuple, baseline_slippage_bps: float) -> dict:
    strategy_id, variant_id, direction, rule_id = key
    x = summary[
        summary["strategy_id"].eq(strategy_id)
        & summary["variant_id"].eq(variant_id)
        & summary["direction"].eq(direction)
        & summary["rule_id"].eq(rule_id)
        & summary["split"].eq(split)
    ].copy()
    if x.empty:
        return {}
    if "slippage_bps" in x.columns:
        exact = x[pd.to_numeric(x["slippage_bps"], errors="coerce").eq(float(baseline_slippage_bps))]
        if not exact.empty:
            x = exact
        else:
            x["_slip_dist"] = (pd.to_numeric(x["slippage_bps"], errors="coerce") - float(baseline_slippage_bps)).abs()
            x = x.sort_values("_slip_dist").head(1)
    row = x.iloc[0]
    fields = (
        "n", "profit_factor", "expectancy", "median_return", "max_drawdown",
        "stop_pct", "target_pct", "max_hold_minutes", "target_r_multiple", "hold_to_eod",
    )
    return {name: row.get(name) for name in fields if name in row.index}


def rank_strategies(
    summary: pd.DataFrame,
    min_n: int = 20,
    baseline_slippage_bps: float = 25.0,
) -> pd.DataFrame:
    """Rank fixed strategy/rule identities using validation data only.

    Test and forward metrics are joined after the selection score is computed so
    they can be inspected without influencing rule choice.
    """
    if summary.empty:
        return pd.DataFrame()
    required = {"strategy_id", "variant_id", "direction", "rule_id", "split", "n", "profit_factor", "expectancy"}
    missing = required - set(summary.columns)
    if missing:
        raise ValueError(f"summary missing required columns: {sorted(missing)}")

    x = summary.copy()
    identity_cols = ["strategy_id", "variant_id", "direction", "rule_id"]
    identities = x[identity_cols].drop_duplicates().itertuples(index=False, name=None)
    rows: list[dict] = []

    for key in identities:
        validation = _split_metric(x, "validation", key, baseline_slippage_bps)
        if not validation:
            continue
        n = int(_num(validation.get("n"), 0))
        if n < int(min_n):
            continue

        strategy_id, variant_id, direction, rule_id = key
        validation_all_slippage = x[
            x["strategy_id"].eq(strategy_id)
            & x["variant_id"].eq(variant_id)
            & x["direction"].eq(direction)
            & x["rule_id"].eq(rule_id)
            & x["split"].eq("validation")
        ]
        slippage_score, last_profitable_bps = _slippage_component(validation_all_slippage)

        pf = _profit_factor_num(validation.get("profit_factor"), 0.0)
        expectancy = _num(validation.get("expectancy"), -1.0)
        median = _num(validation.get("median_return"), 0.0)
        drawdown = _num(validation.get("max_drawdown"), -1.0)

        pf_component = 1.0 if pf == np.inf else _clip01((pf - 1.0) / 1.5)
        expectancy_component = _clip01((expectancy + 0.005) / 0.055)
        sample_component = _clip01(math.log1p(n) / math.log1p(100))
        median_component = _clip01((median + 0.005) / 0.035)
        drawdown_component = 1.0 - _clip01(abs(drawdown) / 0.50)
        robustness_score = (
            0.30 * pf_component
            + 0.25 * expectancy_component
            + 0.15 * sample_component
            + 0.10 * median_component
            + 0.10 * drawdown_component
            + 0.10 * slippage_score
        )

        row = {
            "strategy_id": strategy_id,
            "variant_id": variant_id,
            "direction": direction,
            "rule_id": rule_id,
            "selection_split": "validation",
            "baseline_slippage_bps": float(baseline_slippage_bps),
            "validation_n": n,
            "validation_profit_factor": pf,
            "validation_expectancy": expectancy,
            "validation_median_return": median,
            "validation_max_drawdown": drawdown,
            "slippage_last_pf_ge_1_0_bps": last_profitable_bps,
            "pf_component": pf_component,
            "expectancy_component": expectancy_component,
            "sample_component": sample_component,
            "median_component": median_component,
            "drawdown_component": drawdown_component,
            "slippage_component": slippage_score,
            "robustness_score": float(robustness_score),
        }
        for field in ("stop_pct", "target_pct", "max_hold_minutes", "target_r_multiple", "hold_to_eod"):
            if field in validation:
                row[field] = validation.get(field)
        for split in ("development", "test", "forward"):
            metrics = _split_metric(x, split, key, baseline_slippage_bps)
            row[f"{split}_n"] = int(_num(metrics.get("n"), 0)) if metrics else 0
            row[f"{split}_profit_factor"] = _profit_factor_num(metrics.get("profit_factor")) if metrics else np.nan
            row[f"{split}_expectancy"] = _num(metrics.get("expectancy")) if metrics else np.nan
        rows.append(row)

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(
        ["robustness_score", "validation_profit_factor", "validation_expectancy", "validation_n"],
        ascending=[False, False, False, False],
    ).reset_index(drop=True)
