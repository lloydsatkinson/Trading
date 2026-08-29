from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


POSITION_GBP = 1_000.0

VARIANTS = {
    "ALL": lambda d: pd.Series(True, index=d.index),
    "LEO_BOTH_ALL": lambda d: d["population"].eq("BOTH"),
    "LEO_BOTH_MIDDAY": lambda d: d["population"].eq("BOTH") & d["ignition_window"].eq("10:30-15:00"),
    "LEO_BOTH_AH": lambda d: d["population"].eq("BOTH") & d["ignition_window"].eq("16:00-20:00"),
    "MORNING_OBSERVATION": lambda d: d["ignition_window"].eq("09:30-10:30"),
}


def apply_variant(df: pd.DataFrame, variant: str) -> pd.DataFrame:
    if variant not in VARIANTS:
        raise KeyError(f"Unknown variant: {variant}")
    if df.empty:
        return df.copy()
    return df.loc[VARIANTS[variant](df)].copy()


def profit_factor(returns: pd.Series) -> float:
    s = pd.to_numeric(returns, errors="coerce").dropna()
    gross_profit = float(s[s > 0].sum())
    gross_loss = float(-s[s < 0].sum())
    if gross_loss == 0:
        return np.inf if gross_profit > 0 else np.nan
    return gross_profit / gross_loss


def _first_numeric(g: pd.DataFrame, col: str) -> float:
    if col not in g.columns:
        return np.nan
    s = pd.to_numeric(g[col], errors="coerce").dropna()
    return float(s.iloc[0]) if not s.empty else np.nan


def _first_value(g: pd.DataFrame, col: str):
    if col not in g.columns:
        return None
    s = g[col].dropna()
    return s.iloc[0] if not s.empty else None


def _replay_metrics(g: pd.DataFrame) -> dict | None:
    returns = pd.to_numeric(g["return_pct"], errors="coerce").dropna()
    if returns.empty:
        return None
    stop_pct = _first_numeric(g, "stop_pct")
    return {
        "stop_pct": stop_pct,
        "target_pct": _first_numeric(g, "target_pct"),
        "max_hold_minutes": _first_numeric(g, "max_hold_minutes"),
        "n": int(len(returns)),
        "expectancy": float(returns.mean()),
        "median_return": float(returns.median()),
        "win_rate": float((returns > 0).mean()),
        "profit_factor": float(profit_factor(returns)),
        "avg_pnl_gbp_1000": float(returns.mean() * POSITION_GBP),
        "median_pnl_gbp_1000": float(returns.median() * POSITION_GBP),
        "worst_pnl_gbp_1000": float(returns.min() * POSITION_GBP),
        "best_pnl_gbp_1000": float(returns.max() * POSITION_GBP),
        "planned_stop_gbp_1000": float(stop_pct * POSITION_GBP) if np.isfinite(stop_pct) else np.nan,
    }


def summarize_replays(replays: pd.DataFrame) -> pd.DataFrame:
    if replays.empty:
        return pd.DataFrame()
    rows = []
    dims = ["variant", "split", "rule_id"]
    for keys, g in replays.groupby(dims, dropna=False):
        metrics = _replay_metrics(g)
        if metrics is None:
            continue
        rows.append({
            "variant": keys[0],
            "split": keys[1],
            "rule_id": keys[2],
            **metrics,
        })
    return pd.DataFrame(rows)


def summarize_replays_by_market_cap(replays: pd.DataFrame) -> pd.DataFrame:
    if replays.empty or "market_cap_bucket" not in replays.columns:
        return pd.DataFrame()
    rows = []
    dims = ["market_cap_bucket", "variant", "split", "rule_id"]
    for keys, g in replays.groupby(dims, dropna=False):
        metrics = _replay_metrics(g)
        if metrics is None:
            continue
        rows.append({
            "market_cap_bucket": keys[0] if pd.notna(keys[0]) else "UNKNOWN",
            "variant": keys[1],
            "split": keys[2],
            "rule_id": keys[3],
            **metrics,
        })
    return pd.DataFrame(rows)


def select_best_hold_times(replays: pd.DataFrame, min_n: int = 8) -> pd.DataFrame:
    """Pick the highest-average-P/L hold for each variant/stop/target.

    Only development and validation trades are eligible for rule selection.
    Forward/test rows may be reported elsewhere but cannot influence the chosen
    hold duration.
    """
    if replays.empty:
        return pd.DataFrame()
    required = {"variant", "split", "stop_pct", "target_pct", "max_hold_minutes", "return_pct"}
    if not required.issubset(replays.columns):
        return pd.DataFrame()

    train = replays[replays["split"].isin(["development", "validation"])].copy()
    if train.empty:
        return pd.DataFrame()

    rows = []
    dims = ["variant", "stop_pct", "target_pct", "max_hold_minutes"]
    for keys, g in train.groupby(dims, dropna=False):
        metrics = _replay_metrics(g)
        if metrics is None or metrics["n"] < min_n:
            continue
        rows.append({
            "variant": keys[0],
            "rule_id": _first_value(g, "rule_id"),
            **metrics,
            "selection_splits": "development+validation",
        })

    candidates = pd.DataFrame(rows)
    if candidates.empty:
        return candidates
    candidates = candidates.sort_values(
        ["variant", "stop_pct", "target_pct", "avg_pnl_gbp_1000", "profit_factor", "n", "max_hold_minutes"],
        ascending=[True, True, True, False, False, False, True],
    )
    return candidates.groupby(["variant", "stop_pct", "target_pct"], as_index=False, sort=False).head(1).reset_index(drop=True)


def summarize_peak_timing(replays: pd.DataFrame) -> pd.DataFrame:
    """Summarize exact same-session time-to-peak once per signal/variant."""
    if replays.empty or not {"peak_return_pct", "minutes_to_peak", "variant", "split"}.issubset(replays.columns):
        return pd.DataFrame()

    signal_key = [c for c in ["symbol", "date", "variant", "split"] if c in replays.columns]
    if not signal_key:
        return pd.DataFrame()
    signals = replays.drop_duplicates(signal_key).copy()

    group_dims = ["variant", "split"]
    if "market_cap_bucket" in signals.columns:
        signals["market_cap_bucket"] = signals["market_cap_bucket"].fillna("UNKNOWN")
        group_dims.append("market_cap_bucket")

    rows = []
    for keys, g in signals.groupby(group_dims, dropna=False):
        peak = pd.to_numeric(g["peak_return_pct"], errors="coerce")
        mins = pd.to_numeric(g["minutes_to_peak"], errors="coerce")
        valid = peak.notna() & mins.notna()
        if not valid.any():
            continue
        peak = peak[valid]
        mins = mins[valid]
        if not isinstance(keys, tuple):
            keys = (keys,)
        row = {
            "variant": keys[0],
            "split": keys[1],
            "n_signals": int(valid.sum()),
            "mean_peak_return_pct": float(peak.mean()),
            "median_peak_return_pct": float(peak.median()),
            "avg_peak_pnl_gbp_1000": float(peak.mean() * POSITION_GBP),
            "mean_minutes_to_peak": float(mins.mean()),
            "median_minutes_to_peak": float(mins.median()),
        }
        if len(group_dims) == 3:
            row["market_cap_bucket"] = keys[2]
        rows.append(row)
    return pd.DataFrame(rows)


def attach_variants(replays: pd.DataFrame) -> pd.DataFrame:
    if replays.empty:
        return replays.copy()
    frames = []
    for variant in VARIANTS:
        x = apply_variant(replays, variant)
        if x.empty:
            continue
        x = x.copy()
        x["variant"] = variant
        frames.append(x)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def fixed_horizon_summary(ignitions: pd.DataFrame) -> pd.DataFrame:
    if ignitions.empty:
        return pd.DataFrame()
    rows = []
    for variant in VARIANTS:
        v = apply_variant(ignitions, variant)
        if v.empty:
            continue
        for split, g in v.groupby("split", dropna=False):
            row = {"variant": variant, "split": split, "n": len(g)}
            for col in ("ret_60m", "ret_120m", "mfe_to_2000", "mae_to_2000"):
                if col in g:
                    s = pd.to_numeric(g[col], errors="coerce")
                    row[f"mean_{col}"] = float(s.mean())
                    row[f"median_{col}"] = float(s.median())
                    if col.startswith("ret_"):
                        row[f"pf_{col}"] = float(profit_factor(s))
            rows.append(row)
    return pd.DataFrame(rows)


def build_latest_results(run_meta: dict, ignitions: pd.DataFrame, replay_summary: pd.DataFrame) -> dict:
    latest_day = str(ignitions["date"].max()) if not ignitions.empty else run_meta.get("end_date")
    latest = ignitions[ignitions["date"].astype(str).eq(latest_day)].copy() if not ignitions.empty else pd.DataFrame()
    tradable = latest[
        latest["population"].eq("BOTH")
        & latest["ignition_window"].isin(["10:30-15:00", "16:00-20:00"])
    ] if not latest.empty else pd.DataFrame()

    best_rules = []
    if not replay_summary.empty:
        train = replay_summary[
            replay_summary["split"].isin(["development", "validation"])
            & replay_summary["variant"].isin(["LEO_BOTH_MIDDAY", "LEO_BOTH_AH"])
            & (replay_summary["n"] >= 8)
        ].copy()
        if not train.empty:
            train = train.sort_values(["profit_factor", "expectancy", "n"], ascending=[False, False, False])
            best_rules = train.head(5).replace({np.inf: None, -np.inf: None}).to_dict("records")

    cap_counts = {}
    if not latest.empty and "market_cap_bucket" in latest.columns:
        cap_counts = latest["market_cap_bucket"].fillna("UNKNOWN").value_counts().to_dict()

    return {
        "run": run_meta,
        "research_status": {
            "leo_is_event_selector": True,
            "morning_0930_1030": "OBSERVE_ONLY",
            "priority_variants": ["LEO_BOTH_MIDDAY", "LEO_BOTH_AH"],
            "market_cap_tagging": "PROSPECTIVE_ONLY_FROM_2026-08-28",
            "variable_stop_grid": [0.03, 0.05, 0.07, 0.10, 0.15, 0.20, 0.30, 0.40, 0.50],
            "hold_time_grid_minutes": [5, 10, 15, 30, 45, 60, 90, 120, 180, 240],
            "same_session_exit_cap": "BEFORE_20:00_ET",
            "time_to_peak": "EXACT_MINUTE_BAR_HIGH_FROM_ENTRY_TO_20:00_ET",
            "position_model_gbp": POSITION_GBP,
            "rule_selection": "DEVELOPMENT_VALIDATION_ONLY",
            "note": "Historical 2026-06-03..2026-08-27 test block has already been inspected; future data is the prospective holdout.",
        },
        "latest_day": latest_day,
        "latest_market_cap_counts": cap_counts,
        "latest_tradable_ignitions": tradable[[
            c for c in [
                "symbol", "date", "timestamp", "population", "ignition_window", "entry_price_slipped",
                "market_cap", "market_cap_bucket", "is_microcap", "market_cap_source", "market_cap_asof",
            ] if c in tradable.columns
        ]].to_dict("records") if not tradable.empty else [],
        "best_development_validation_rules": best_rules,
    }


def write_json(path: str | Path, payload: dict) -> None:
    Path(path).write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def build_shortlist(candidates: pd.DataFrame, transitions: pd.DataFrame, ignitions: pd.DataFrame) -> pd.DataFrame:
    if candidates.empty:
        return pd.DataFrame()

    latest_day = str(candidates["date"].astype(str).max())
    out = candidates[candidates["date"].astype(str).eq(latest_day)].copy()
    state_rank = {"DISCOVERED": 1, "SHORTS_BUILDING": 2, "ABSORPTION": 3, "ARMED": 4, "IGNITION": 5}

    if not transitions.empty:
        t = transitions[transitions["date"].astype(str).eq(latest_day)].copy()
        t["state_rank"] = t["state"].map(state_rank).fillna(0)
        t = t.sort_values(["symbol", "state_rank", "timestamp"]).groupby("symbol", as_index=False).tail(1)
        out = out.merge(t[["symbol", "state", "timestamp", "state_rank"]], on="symbol", how="left")
    else:
        out["state"] = "DISCOVERED"
        out["timestamp"] = None
        out["state_rank"] = 1

    if not ignitions.empty:
        i = ignitions[ignitions["date"].astype(str).eq(latest_day)].copy()
        keep = [c for c in ["symbol", "ignition_window", "entry_price_slipped"] if c in i.columns]
        if keep:
            out = out.merge(i[keep].drop_duplicates("symbol"), on="symbol", how="left")

    def action(row) -> str:
        if row.get("population") == "BOTH" and row.get("ignition_window") in {"10:30-15:00", "16:00-20:00"}:
            return "TRADABLE_RESEARCH_SIGNAL"
        if row.get("population") == "BOTH" and row.get("state") in {"ABSORPTION", "ARMED", "IGNITION"}:
            return "WATCH"
        if row.get("ignition_window") == "09:30-10:30":
            return "OBSERVE_TRAP"
        return "NO_ACTION"

    out["action"] = out.apply(action, axis=1)
    action_rank = {"TRADABLE_RESEARCH_SIGNAL": 4, "WATCH": 3, "OBSERVE_TRAP": 2, "NO_ACTION": 1}
    out["action_rank"] = out["action"].map(action_rank).fillna(0)
    out["population_rank"] = out["population"].map({"BOTH": 4, "LEO_PM": 3, "LEO_OPEN": 2, "NEITHER_CONTROL": 1}).fillna(0)
    sort_col = "open30_dollar_turnover" if "open30_dollar_turnover" in out.columns else "symbol"
    ascending = [False, False, False, False] if sort_col == "open30_dollar_turnover" else [False, False, False, True]
    out = out.sort_values(["action_rank", "population_rank", "state_rank", sort_col], ascending=ascending)
    return out.reset_index(drop=True)
