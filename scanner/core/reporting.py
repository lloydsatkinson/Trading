from __future__ import annotations

from typing import Any, Iterable

import numpy as np
import pandas as pd


def profit_factor(returns: pd.Series | Iterable[float]) -> float:
    values = pd.to_numeric(pd.Series(list(returns) if not isinstance(returns, pd.Series) else returns), errors="coerce").dropna()
    if values.empty:
        return np.nan
    gross_wins = float(values[values > 0].sum())
    gross_losses = float(-values[values < 0].sum())
    if gross_losses == 0:
        return np.inf if gross_wins > 0 else np.nan
    return round(gross_wins / gross_losses, 12)


def max_drawdown(returns: pd.Series | Iterable[float]) -> float:
    values = pd.to_numeric(pd.Series(list(returns) if not isinstance(returns, pd.Series) else returns), errors="coerce").fillna(0.0)
    if values.empty:
        return np.nan
    equity = (1.0 + values).cumprod()
    peaks = equity.cummax()
    drawdown = equity / peaks - 1.0
    return float(drawdown.min())


def _mean_or_nan(group: pd.DataFrame, column: str) -> float:
    if column not in group.columns:
        return np.nan
    values = pd.to_numeric(group[column], errors="coerce")
    return float(values.mean()) if values.notna().any() else np.nan


def _median_or_nan(group: pd.DataFrame, column: str) -> float:
    if column not in group.columns:
        return np.nan
    values = pd.to_numeric(group[column], errors="coerce")
    return float(values.median()) if values.notna().any() else np.nan


def summarize_strategy_replays(replays: pd.DataFrame, segment_cols: Iterable[str] = ()) -> pd.DataFrame:
    if replays.empty:
        return pd.DataFrame()
    required = {"strategy_id", "variant_id", "direction", "split", "rule_id", "return_pct"}
    missing = required - set(replays.columns)
    if missing:
        raise ValueError(f"replays missing required columns: {sorted(missing)}")
    x = replays.copy()
    base_groups = ["strategy_id", "variant_id", "direction", "split", "rule_id"]
    if "slippage_bps" in x.columns:
        base_groups.append("slippage_bps")
    for col in segment_cols:
        if col in x.columns and col not in base_groups:
            base_groups.append(col)
    rows: list[dict[str, Any]] = []
    for keys, group in x.groupby(base_groups, dropna=False, sort=False):
        keys = keys if isinstance(keys, tuple) else (keys,)
        row = dict(zip(base_groups, keys))
        returns = pd.to_numeric(group["return_pct"], errors="coerce").dropna()
        n = int(len(returns))
        unique_days = int(group["date"].astype(str).nunique()) if "date" in group.columns and not group.empty else 0
        expectancy = float(returns.mean()) if n else np.nan
        median_return = float(returns.median()) if n else np.nan
        row.update({
            "n": n,
            "trades_per_day": float(n / unique_days) if unique_days else np.nan,
            "expectancy": expectancy,
            "median_return": median_return,
            "win_rate": float((returns > 0).mean()) if n else np.nan,
            "profit_factor": profit_factor(returns),
            "mean_r": _mean_or_nan(group, "r_multiple"),
            "median_r": _median_or_nan(group, "r_multiple"),
            "mean_mfe": _mean_or_nan(group, "mfe_pct"),
            "mean_mae": _mean_or_nan(group, "mae_pct"),
            "max_drawdown": max_drawdown(returns),
            "avg_pnl_gbp_1000": expectancy * 1000.0 if np.isfinite(expectancy) else np.nan,
            "median_pnl_gbp_1000": median_return * 1000.0 if np.isfinite(median_return) else np.nan,
            "worst_pnl_gbp_1000": float(returns.min() * 1000.0) if n else np.nan,
            "eligible_n20": n >= 20,
            "eligible_n50": n >= 50,
            "eligible_n100": n >= 100,
        })
        for source in ("stop_pct", "target_pct", "max_hold_minutes", "target_r_multiple", "hold_to_eod"):
            if source in group.columns:
                non_null = group[source].dropna()
                row[source] = non_null.iloc[0] if not non_null.empty else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def _first_bps(table: pd.DataFrame, predicate) -> float:
    matched = table[predicate(table["profit_factor"])]
    return float(matched.iloc[0]["slippage_bps"]) if not matched.empty else np.nan


def slippage_resilience(table: pd.DataFrame) -> dict[str, float]:
    if table.empty or not {"slippage_bps", "profit_factor"}.issubset(table.columns):
        return {"pf_below_1_2_bps": np.nan, "pf_below_1_0_bps": np.nan, "last_pf_ge_1_0_bps": np.nan}
    x = table[["slippage_bps", "profit_factor"]].copy()
    x["slippage_bps"] = pd.to_numeric(x["slippage_bps"], errors="coerce")
    x["profit_factor"] = pd.to_numeric(x["profit_factor"], errors="coerce")
    x = x.dropna().sort_values("slippage_bps")
    if x.empty:
        return {"pf_below_1_2_bps": np.nan, "pf_below_1_0_bps": np.nan, "last_pf_ge_1_0_bps": np.nan}
    resilient = x[x["profit_factor"] >= 1.0]
    return {
        "pf_below_1_2_bps": _first_bps(x, lambda s: s < 1.2),
        "pf_below_1_0_bps": _first_bps(x, lambda s: s < 1.0),
        "last_pf_ge_1_0_bps": float(resilient.iloc[-1]["slippage_bps"]) if not resilient.empty else np.nan,
    }
