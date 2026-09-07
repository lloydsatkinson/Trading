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
RULE_KEY = ["strategy_id", "variant_id", "direction", "rule_id"]


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


def _selected_rule_replays(replays: pd.DataFrame, selected_rules: pd.DataFrame) -> pd.DataFrame:
    x = _prepare(replays)
    if x.empty or selected_rules.empty or not set(RULE_KEY).issubset(selected_rules.columns):
        return pd.DataFrame()
    chosen = selected_rules[RULE_KEY].copy()
    chosen = chosen[chosen["strategy_id"].astype(str).eq("MERCILESS_Q")]
    chosen = chosen.drop_duplicates(RULE_KEY)
    if chosen.empty:
        return pd.DataFrame()
    out = x.merge(chosen, on=RULE_KEY, how="inner")
    if not out.empty:
        out["selected_rule_id"] = out["rule_id"]
    return out


def _sequence_bucket(value: Any) -> str:
    try:
        sequence = int(float(value))
    except (TypeError, ValueError):
        return "UNKNOWN"
    if sequence <= 0:
        return "UNKNOWN"
    if sequence >= 5:
        return "5+"
    return str(sequence)


def summarize_sequence_edge(
    replays: pd.DataFrame,
    baseline_slippage_bps: float = 25.0,
) -> pd.DataFrame:
    """Fine-grained Merciless-Q expectancy separately for every exact re-entry number."""
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


def sequence_bucket_summary(
    replays: pd.DataFrame,
    selected_rules: pd.DataFrame,
    baseline_slippage_bps: float = 25.0,
) -> pd.DataFrame:
    """Design-level repeat-entry summary using validation-selected rules only.

    Rule selection happens upstream on the validation/25-bps leaderboard. This
    function never picks a different rule based on test, forward or friction data.
    """
    x = _selected_rule_replays(replays, selected_rules)
    if x.empty:
        return pd.DataFrame()
    x = x[np.isclose(x["slippage_bps"], float(baseline_slippage_bps))].copy()
    if x.empty:
        return pd.DataFrame()
    x["sequence_bucket"] = x["sequence_number"].map(_sequence_bucket)
    dims = ["strategy_id", "variant_id", "direction", "split", "selected_rule_id", "sequence_bucket"]
    bucket_order = {"1": 1, "2": 2, "3": 3, "4": 4, "5+": 5, "UNKNOWN": 99}
    rows: list[dict[str, Any]] = []
    for keys, group in x.groupby(dims, dropna=False, sort=False):
        returns = pd.to_numeric(group["return_pct"], errors="coerce").dropna()
        if returns.empty:
            continue
        row = dict(zip(dims, keys if isinstance(keys, tuple) else (keys,)))
        peak = pd.to_numeric(group["peak_return_pct"], errors="coerce") if "peak_return_pct" in group.columns else pd.Series(dtype=float)
        mins = pd.to_numeric(group["minutes_to_peak"], errors="coerce") if "minutes_to_peak" in group.columns else pd.Series(dtype=float)
        row.update({
            "baseline_slippage_bps": float(baseline_slippage_bps),
            "n": int(len(returns)),
            "expectancy": float(returns.mean()),
            "median_return": float(returns.median()),
            "win_rate": float((returns > 0).mean()),
            "profit_factor": profit_factor(returns),
            "mean_peak_return_pct": float(peak.mean()) if peak.notna().any() else np.nan,
            "median_peak_return_pct": float(peak.median()) if peak.notna().any() else np.nan,
            "median_minutes_to_peak": float(mins.median()) if mins.notna().any() else np.nan,
        })
        rows.append(row)
    out = pd.DataFrame(rows)
    if not out.empty:
        out["_bucket_order"] = out["sequence_bucket"].map(bucket_order).fillna(99)
        out = out.sort_values(["strategy_id", "variant_id", "direction", "split", "_bucket_order"]).drop(columns="_bucket_order").reset_index(drop=True)
    return out


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
    """Fine-grained expectancy break-even for every rule and exact sequence number."""
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


def friction_threshold_summary(replays: pd.DataFrame, selected_rules: pd.DataFrame) -> pd.DataFrame:
    """PF/expectancy resilience of the validation-selected rule across friction."""
    x = _selected_rule_replays(replays, selected_rules)
    if x.empty:
        return pd.DataFrame()
    dims = ["strategy_id", "variant_id", "direction", "split", "selected_rule_id"]
    rows: list[dict[str, Any]] = []
    for keys, group in x.groupby(dims, dropna=False, sort=False):
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
        pf1 = curve[curve["profit_factor"] >= 1.0]
        pf125 = curve[curve["profit_factor"] >= 1.25]
        positive = curve[curve["expectancy"] > 0]
        row = dict(zip(dims, keys if isinstance(keys, tuple) else (keys,)))
        row.update({
            "grid_min_bps": float(curve["slippage_bps"].min()),
            "grid_max_bps": float(curve["slippage_bps"].max()),
            "last_pf_ge_1_0_bps": float(pf1.iloc[-1]["slippage_bps"]) if not pf1.empty else np.nan,
            "last_pf_ge_1_25_bps": float(pf125.iloc[-1]["slippage_bps"]) if not pf125.empty else np.nan,
            "last_positive_expectancy_bps": float(positive.iloc[-1]["slippage_bps"]) if not positive.empty else np.nan,
        })
        rows.append(row)
    return pd.DataFrame(rows)
