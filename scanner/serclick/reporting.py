from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


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


def summarize_replays(replays: pd.DataFrame) -> pd.DataFrame:
    if replays.empty:
        return pd.DataFrame()
    rows = []
    dims = ["variant", "split", "rule_id"]
    for keys, g in replays.groupby(dims, dropna=False):
        returns = pd.to_numeric(g["return_pct"], errors="coerce").dropna()
        if returns.empty:
            continue
        rows.append({
            "variant": keys[0],
            "split": keys[1],
            "rule_id": keys[2],
            "n": int(len(returns)),
            "expectancy": float(returns.mean()),
            "median_return": float(returns.median()),
            "win_rate": float((returns > 0).mean()),
            "profit_factor": float(profit_factor(returns)),
        })
    return pd.DataFrame(rows)


def summarize_replays_by_market_cap(replays: pd.DataFrame) -> pd.DataFrame:
    if replays.empty or "market_cap_bucket" not in replays.columns:
        return pd.DataFrame()
    rows = []
    dims = ["market_cap_bucket", "variant", "split", "rule_id"]
    for keys, g in replays.groupby(dims, dropna=False):
        returns = pd.to_numeric(g["return_pct"], errors="coerce").dropna()
        if returns.empty:
            continue
        rows.append({
            "market_cap_bucket": keys[0] if pd.notna(keys[0]) else "UNKNOWN",
            "variant": keys[1],
            "split": keys[2],
            "rule_id": keys[3],
            "n": int(len(returns)),
            "expectancy": float(returns.mean()),
            "median_return": float(returns.median()),
            "win_rate": float((returns > 0).mean()),
            "profit_factor": float(profit_factor(returns)),
        })
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
