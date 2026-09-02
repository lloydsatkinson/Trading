from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from scanner.core.reporting import profit_factor

GROUP_DIMS = [
    "strategy_id",
    "variant_id",
    "direction",
    "split",
    "rule_id",
    "sequence_number",
]


def _prepare(replays: pd.DataFrame) -> pd.DataFrame:
    required = set(GROUP_DIMS) | {"slippage_bps", "return_pct"}
    if replays.empty or not required.issubset(replays.columns):
        return pd.DataFrame()
    x = replays.copy()
    x = x[x["strategy_id"].astype(str).eq("MERCILESS_Q")]
    if x.empty:
        return x
    x["sequence_number"] = pd.to_numeric(x["sequence_number"], errors="coerce")
    x["slippage_bps"] = pd.to_numeric(x["slippage_bps"], errors="coerce")
    x["return_pct"] = pd.to_numeric(x["return_pct"], errors="coerce")
    return x.dropna(subset=["sequence_number", "slippage_bps", "return_pct"])


def summarize_sequence_edge(
    replays: pd.DataFrame,
    baseline_slippage_bps: float = 25.0,
) -> pd.DataFrame:
    """Summarize Merciless-Q expectancy separately for each re-entry number.

    The baseline friction slice is intentionally fixed before grouping so entry 1,
    entry 2, etc. can be compared without mixing different execution assumptions.
    """
    x = _prepare(replays)
    if x.empty:
        return pd.DataFrame()
    x = x[np.isclose(x["slippage_bps"], float(baseline_slippage_bps))].copy()
    if x.empty:
        return pd.DataFrame()

    rows: list[dict[str, Any]] = []
    for keys, group in x.groupby(GROUP_DIMS, dropna=False, sort=False):
        returns = pd.to_numeric(group["return_pct"], errors="coerce").dropna()
        if returns.empty:
            continue
        row = dict(zip(GROUP_DIMS, keys if isinstance(keys, tuple) else (keys,)))
        unique_days = int(group["date"].astype(str).nunique()) if "date" in group.columns else 0
        row.update({
            "baseline_slippage_bps": float(baseline_slippage_bps),
            "n": int(len(returns)),
            "trades_per_day": float(len(returns) / unique_days) if unique_days else np.nan,
            "expectancy": float(returns.mean()),
            "median_return": float(returns.median()),
            "win_rate": float((returns > 0).mean()),
            "profit_factor": profit_factor(returns),
            "mean_r": float(pd.to_numeric(group["r_multiple"], errors="coerce").mean()) if "r_multiple" in group.columns else np.nan,
            "mean_mfe": float(pd.to_numeric(group["mfe_pct"], errors="coerce").mean()) if "mfe_pct" in group.columns else np.nan,
            "mean_mae": float(pd.to_numeric(group["mae_pct"], errors="coerce").mean()) if "mae_pct" in group.columns else np.nan,
        })
        row["positive_edge"] = bool(row["expectancy"] > 0 and row["profit_factor"] >= 1.0)
        rows.append(row)
    return pd.DataFrame(rows)


def _interpolate_zero(low_bps: float, low_exp: float, high_bps: float, high_exp: float) -> float:
    if high_bps <= low_bps:
        return float(low_bps)
    if np.isclose(low_exp, 0.0):
        return float(low_bps)
    if np.isclose(high_exp, 0.0):
        return float(high_bps)
    denominator = high_exp - low_exp
    if np.isclose(denominator, 0.0):
        return np.nan
    fraction = (0.0 - low_exp) / denominator
    return float(low_bps + fraction * (high_bps - low_bps))


def friction_break_even(replays: pd.DataFrame) -> pd.DataFrame:
    """Estimate adverse-entry-slippage bps where mean expectancy crosses zero.

    Uses the tested slippage grid and linearly interpolates only between the last
    positive-expectancy point and the next non-positive point. It does not
    extrapolate beyond the observed grid.
    """
    x = _prepare(replays)
    if x.empty:
        return pd.DataFrame()

    rows: list[dict[str, Any]] = []
    for keys, group in x.groupby(GROUP_DIMS, dropna=False, sort=False):
        curve_rows = []
        for bps, friction_group in group.groupby("slippage_bps", sort=True):
            returns = pd.to_numeric(friction_group["return_pct"], errors="coerce").dropna()
            if returns.empty:
                continue
            curve_rows.append({
                "slippage_bps": float(bps),
                "n": int(len(returns)),
                "expectancy": float(returns.mean()),
                "profit_factor": profit_factor(returns),
            })
        curve = pd.DataFrame(curve_rows).sort_values("slippage_bps").reset_index(drop=True)
        if curve.empty:
            continue

        positive = curve[curve["expectancy"] > 0]
        last_positive_bps = float(positive.iloc[-1]["slippage_bps"]) if not positive.empty else np.nan
        first_nonpositive_bps = np.nan
        break_even_bps = np.nan
        low_exp = np.nan
        high_exp = np.nan
        status = "NO_POSITIVE_EDGE"

        if not positive.empty:
            low_idx = int(positive.index[-1])
            low = curve.loc[low_idx]
            later = curve.loc[curve.index > low_idx]
            nonpositive_later = later[later["expectancy"] <= 0]
            if not nonpositive_later.empty:
                high = nonpositive_later.iloc[0]
                first_nonpositive_bps = float(high["slippage_bps"])
                low_exp = float(low["expectancy"])
                high_exp = float(high["expectancy"])
                break_even_bps = _interpolate_zero(
                    float(low["slippage_bps"]),
                    low_exp,
                    float(high["slippage_bps"]),
                    high_exp,
                )
                status = "CROSSES_WITHIN_GRID"
            else:
                status = "SURVIVES_MAX_TESTED"
        else:
            first_nonpositive_bps = float(curve.iloc[0]["slippage_bps"])
            high_exp = float(curve.iloc[0]["expectancy"])

        row = dict(zip(GROUP_DIMS, keys if isinstance(keys, tuple) else (keys,)))
        row.update({
            "grid_min_bps": float(curve["slippage_bps"].min()),
            "grid_max_bps": float(curve["slippage_bps"].max()),
            "last_positive_grid_bps": last_positive_bps,
            "first_nonpositive_grid_bps": first_nonpositive_bps,
            "break_even_bps": break_even_bps,
            "expectancy_at_low_bps": low_exp,
            "expectancy_at_high_bps": high_exp,
            "friction_status": status,
        })
        rows.append(row)
    return pd.DataFrame(rows)
