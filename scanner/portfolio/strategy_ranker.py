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


def _identity_columns(summary: pd.DataFrame) -> list[str]:
    cols = ["strategy_id", "variant_id", "direction", "rule_id"]
    # Signal-qualification thresholds are a separate research identity from the
    # replay/exit rule. Preserve them whenever the summary supplies setup_id.
    if "setup_id" in summary.columns:
        cols.append("setup_id")
    return cols


def _identity_mask(summary: pd.DataFrame, identity_cols: list[str], key: tuple) -> pd.Series:
    mask = pd.Series(True, index=summary.index)
    for column, value in zip(identity_cols, key):
        if pd.isna(value):
            mask &= summary[column].isna()
        else:
            mask &= summary[column].eq(value)
    return mask


def _split_metric(
    summary: pd.DataFrame,
    split: str,
    identity_cols: list[str],
    key: tuple,
    baseline_slippage_bps: float,
) -> dict:
    x = summary[_identity_mask(summary, identity_cols, key) & summary["split"].eq(split)].copy()
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
        "stop_mode", "stop_pct", "target_pct", "max_hold_minutes", "max_hold_sessions",
        "target_r_multiple", "trailing_exit", "hold_to_eod",
    )
    return {name: row.get(name) for name in fields if name in row.index}


def rank_strategies(
    summary: pd.DataFrame,
    min_n: int = 20,
    baseline_slippage_bps: float = 25.0,
    production_min_expectancy: float = 0.05,
) -> pd.DataFrame:
    """Rank fixed strategy/setup/rule identities using validation data only.

    Test and forward metrics are joined after the selection score is computed so
    they can be inspected without influencing rule choice. Research candidates
    remain visible even when they fail the production hurdle; production_eligible
    requires validation expectancy to meet production_min_expectancy at the
    baseline slippage assumption.
    """
    if summary.empty:
        return pd.DataFrame()
    required = {"strategy_id", "variant_id", "direction", "rule_id", "split", "n", "profit_factor", "expectancy"}
    missing = required - set(summary.columns)
    if missing:
        raise ValueError(f"summary missing required columns: {sorted(missing)}")

    x = summary.copy()
    identity_cols = _identity_columns(x)
    identities = x[identity_cols].drop_duplicates().itertuples(index=False, name=None)
    rows: list[dict] = []

    for key in identities:
        validation = _split_metric(x, "validation", identity_cols, key, baseline_slippage_bps)
        if not validation:
            continue
        n = int(_num(validation.get("n"), 0))
        if n < int(min_n):
            continue

        identity = dict(zip(identity_cols, key))
        validation_all_slippage = x[
            _identity_mask(x, identity_cols, key) & x["split"].eq("validation")
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
        production_eligible = bool(expectancy >= float(production_min_expectancy))

        row = {
            **identity,
            "selection_split": "validation",
            "baseline_slippage_bps": float(baseline_slippage_bps),
            "production_min_expectancy": float(production_min_expectancy),
            "production_eligible": production_eligible,
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
        for field in (
            "stop_mode", "stop_pct", "target_pct", "max_hold_minutes", "max_hold_sessions",
            "target_r_multiple", "trailing_exit", "hold_to_eod",
        ):
            if field in validation:
                row[field] = validation.get(field)
        for split in ("development", "test", "forward"):
            metrics = _split_metric(x, split, identity_cols, key, baseline_slippage_bps)
            row[f"{split}_n"] = int(_num(metrics.get("n"), 0)) if metrics else 0
            row[f"{split}_profit_factor"] = _profit_factor_num(metrics.get("profit_factor")) if metrics else np.nan
            row[f"{split}_expectancy"] = _num(metrics.get("expectancy")) if metrics else np.nan
        rows.append(row)

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(
        ["production_eligible", "robustness_score", "validation_profit_factor", "validation_expectancy", "validation_n"],
        ascending=[False, False, False, False, False],
    ).reset_index(drop=True)
