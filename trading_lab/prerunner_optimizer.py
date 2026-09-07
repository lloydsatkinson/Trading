from __future__ import annotations

import math
from typing import Sequence

import numpy as np
import pandas as pd


def development_thresholds(
    frame: pd.DataFrame,
    features: Sequence[str],
    quantiles: Sequence[float] = (0.50, 0.65, 0.80, 0.90),
    split_col: str = "split",
    development_label: str = "development",
) -> pd.DataFrame:
    """Return thresholds learned strictly from the development split."""
    if split_col not in frame.columns:
        raise ValueError(f"missing {split_col}")
    dev = frame[frame[split_col] == development_label]
    rows = []
    for feature in features:
        if feature not in dev.columns:
            continue
        values = pd.to_numeric(dev[feature], errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
        if values.empty:
            continue
        for q in quantiles:
            if not 0 <= float(q) <= 1:
                raise ValueError("quantiles must be between 0 and 1")
            rows.append({"feature": feature, "quantile": float(q), "threshold": float(values.quantile(float(q)))})
    return pd.DataFrame(rows, columns=["feature", "quantile", "threshold"])


def performance_metrics(trades: pd.DataFrame, side: str, sessions: int) -> dict:
    """Cost-adjusted trade metrics for one side only.

    The caller supplies already-costed return_r values; mixing LONG and SHORT is
    deliberately rejected by filtering on the requested side.
    """
    side = str(side).upper()
    if side not in {"LONG", "SHORT"}:
        raise ValueError("side must be LONG or SHORT")
    if "side" not in trades.columns or "return_r" not in trades.columns:
        raise ValueError("trades requires side and return_r")
    g = trades[trades["side"].astype(str).str.upper() == side]
    r = pd.to_numeric(g["return_r"], errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    n = int(len(r))
    if n == 0:
        return {
            "side": side,
            "n": 0,
            "trades_per_day": 0.0,
            "profit_factor": 0.0,
            "expectancy_r": 0.0,
            "win_rate": 0.0,
            "max_drawdown_r": 0.0,
        }
    wins = float(r[r > 0].sum())
    losses = float(-r[r < 0].sum())
    pf = wins / losses if losses > 0 else (math.inf if wins > 0 else 0.0)
    equity = pd.Series([0.0] + r.cumsum().tolist(), dtype=float)
    dd = float((equity.cummax() - equity).max())
    return {
        "side": side,
        "n": n,
        "trades_per_day": float(n / max(1, int(sessions))),
        "profit_factor": float(pf),
        "expectancy_r": float(r.mean()),
        "win_rate": float((r > 0).mean()),
        "max_drawdown_r": dd,
    }


def pareto_frontier(
    frame: pd.DataFrame,
    maximize: Sequence[str] = ("profit_factor", "expectancy_r", "trades_per_day"),
    minimize: Sequence[str] = ("max_drawdown_r",),
) -> pd.DataFrame:
    """Return non-dominated rows across robustness/frequency objectives."""
    if frame.empty:
        return frame.copy()
    needed = set(maximize) | set(minimize)
    missing = needed - set(frame.columns)
    if missing:
        raise ValueError(f"missing {sorted(missing)}")
    x = frame.reset_index(drop=True).copy()
    keep = np.ones(len(x), dtype=bool)
    for i in range(len(x)):
        if not keep[i]:
            continue
        a = x.iloc[i]
        for j in range(len(x)):
            if i == j:
                continue
            b = x.iloc[j]
            no_worse = True
            strictly_better = False
            for c in maximize:
                av, bv = float(a[c]), float(b[c])
                if np.isnan(av) or np.isnan(bv) or bv < av:
                    no_worse = False
                    break
                strictly_better = strictly_better or bv > av
            if not no_worse:
                continue
            for c in minimize:
                av, bv = float(a[c]), float(b[c])
                if np.isnan(av) or np.isnan(bv) or bv > av:
                    no_worse = False
                    break
                strictly_better = strictly_better or bv < av
            if no_worse and strictly_better:
                keep[i] = False
                break
    return x.loc[keep].reset_index(drop=True)
