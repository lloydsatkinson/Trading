from __future__ import annotations

from datetime import date
import hashlib
import math
from typing import Sequence

import numpy as np
import pandas as pd

NY = "America/New_York"


def _bar_date(row: dict) -> date:
    raw = row.get("t") or row.get("timestamp")
    z = pd.Timestamp(raw)
    if z.tzinfo is None:
        z = z.tz_localize("UTC")
    return z.tz_convert(NY).date()


def _num(row: dict, short: str, long: str, default: float = 0.0) -> float:
    try:
        return float(row.get(short, row.get(long, default)) or default)
    except (TypeError, ValueError):
        return float(default)


def daily_prior_context(daily: dict[str, list[dict]], sessions: Sequence[date]) -> dict[tuple[str, date], dict]:
    """Build point-in-time daily context using only sessions before each row.

    Current-day OHLCV is retained for later diagnostics/case labels, but every
    `prior*` field is calculated before the current row is appended to history.
    """
    out: dict[tuple[str, date], dict] = {}
    ordered = list(sorted(sessions))
    for symbol, rows in daily.items():
        ticker = str(symbol).upper()
        by_day = {_bar_date(r): r for r in rows}
        closes: list[float] = []
        volumes: list[float] = []
        for session in ordered:
            row = by_day.get(session)
            if row is None:
                continue
            close = _num(row, "c", "close")
            high = _num(row, "h", "high")
            low = _num(row, "l", "low")
            volume = _num(row, "v", "volume")
            previous_close = closes[-1] if closes else None
            prior20 = volumes[-20:]
            prior20_median = float(np.median(prior20)) if prior20 else None
            prior20_max = float(max(prior20)) if prior20 else None
            prior4d_return = (
                previous_close / closes[-4] - 1.0
                if previous_close and len(closes) >= 4 and closes[-4] > 0
                else None
            )
            out[(ticker, session)] = {
                "previous_close": previous_close,
                "prior20_median_volume": prior20_median,
                "prior20_max_volume": prior20_max,
                "prior4d_return": prior4d_return,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
            }
            if close > 0:
                closes.append(close)
            if volume >= 0:
                volumes.append(volume)
    return out


def _stable_key(session_date: str, ticker: str) -> str:
    return hashlib.sha256(f"{session_date}|{ticker}".encode("utf-8")).hexdigest()


def _numeric(frame: pd.DataFrame, name: str, default: float = np.nan) -> pd.Series:
    if name not in frame.columns:
        return pd.Series(default, index=frame.index, dtype=float)
    return pd.to_numeric(frame[name], errors="coerce").replace([np.inf, -np.inf], np.nan)


def signal_activity_table(snapshots: pd.DataFrame) -> pd.DataFrame:
    """Collapse frozen snapshots into one pre-09:36 activity row per stock/day.

    Only signal-time columns are read. Outcome labels may be present in `snapshots`
    but are intentionally ignored so selection cannot leak the future.
    """
    required = {"session_date", "ticker", "previous_close", "prior20_median_volume"}
    missing = required - set(snapshots.columns)
    if missing:
        raise ValueError(f"missing {sorted(missing)}")
    x = snapshots.copy()
    x["session_date"] = x["session_date"].astype(str)
    x["ticker"] = x["ticker"].astype(str).str.upper()
    x["previous_close"] = _numeric(x, "previous_close")
    x["prior20_median_volume"] = _numeric(x, "prior20_median_volume")
    x["_abs_gap"] = _numeric(x, "pm_gap_pct").abs()
    x["_pm_dollar"] = _numeric(x, "pm_dollar_volume", 0.0).fillna(0.0)
    x["_abs_impulse"] = _numeric(x, "impulse_pct").abs()
    x["_rvol"] = _numeric(x, "open_rvol")
    x["_open_dollar"] = (_numeric(x, "open_cum_volume", 0.0).fillna(0.0) * _numeric(x, "snapshot_price", 0.0).fillna(0.0))

    rows = []
    for (session_date, ticker), g in x.groupby(["session_date", "ticker"], sort=True):
        first = g.iloc[0]
        abs_gap = float(g["_abs_gap"].max(skipna=True)) if g["_abs_gap"].notna().any() else 0.0
        pm_dollar = float(g["_pm_dollar"].max(skipna=True)) if len(g) else 0.0
        abs_impulse = float(g["_abs_impulse"].max(skipna=True)) if g["_abs_impulse"].notna().any() else 0.0
        rvol = float(g["_rvol"].max(skipna=True)) if g["_rvol"].notna().any() else 0.0
        open_dollar = float(g["_open_dollar"].max(skipna=True)) if len(g) else 0.0
        score = (
            4.0 * abs_gap
            + math.log1p(max(0.0, pm_dollar) / 100_000.0)
            + 4.0 * abs_impulse
            + math.log1p(max(0.0, rvol))
            + math.log1p(max(0.0, open_dollar) / 100_000.0)
        )
        rows.append({
            "session_date": session_date,
            "ticker": ticker,
            "previous_close": float(first["previous_close"]) if pd.notna(first["previous_close"]) else np.nan,
            "prior20_median_volume": float(first["prior20_median_volume"]) if pd.notna(first["prior20_median_volume"]) else np.nan,
            "max_abs_pm_gap_pct": abs_gap,
            "max_pm_dollar_volume": pm_dollar,
            "max_abs_impulse_pct": abs_impulse,
            "max_open_rvol": rvol,
            "max_open_dollar_volume": open_dollar,
            "signal_activity_score": float(score),
        })
    return pd.DataFrame(rows)


def select_signal_time_candidates(
    snapshots: pd.DataFrame,
    *,
    min_price: float = 0.75,
    max_price: float = 20.0,
    min_prior_volume: float = 50_000.0,
    min_abs_pm_gap: float = 0.05,
    min_pm_dollar_volume: float = 250_000.0,
    min_abs_open_impulse: float = 0.03,
    min_open_rvol: float = 1.5,
    min_open_dollar_volume: float = 250_000.0,
    max_active: int = 250,
    random_controls: int = 25,
) -> pd.DataFrame:
    """Choose full-day downloads using information available no later than 09:35.

    The active gate is deliberately permissive; a bounded top-N prevents runaway
    data volume. Deterministic quiet controls preserve ordinary-market context.
    No same-day future outcome column is read.
    """
    if max_active < 1 or random_controls < 0:
        raise ValueError("invalid candidate limits")
    a = signal_activity_table(snapshots)
    if a.empty:
        return pd.DataFrame(columns=list(a.columns) + ["selection_role"])
    eligible = a[
        a["previous_close"].between(min_price, max_price, inclusive="both")
        & (a["prior20_median_volume"] >= min_prior_volume)
    ].copy()
    out = []
    for session_date, g in eligible.groupby("session_date", sort=True):
        active_mask = (
            (g["max_abs_pm_gap_pct"] >= min_abs_pm_gap)
            | (g["max_pm_dollar_volume"] >= min_pm_dollar_volume)
            | (g["max_abs_impulse_pct"] >= min_abs_open_impulse)
            | (g["max_open_rvol"] >= min_open_rvol)
            | (g["max_open_dollar_volume"] >= min_open_dollar_volume)
        )
        active = g[active_mask].sort_values(
            ["signal_activity_score", "ticker"], ascending=[False, True]
        ).head(max_active).copy()
        active["selection_role"] = "signal_active"
        out.append(active)

        if random_controls:
            quiet = g[~g["ticker"].isin(set(active["ticker"]))].copy()
            if not quiet.empty:
                quiet["_stable"] = quiet["ticker"].map(lambda t: _stable_key(str(session_date), str(t)))
                quiet = quiet.sort_values(["_stable", "ticker"]).head(random_controls).drop(columns="_stable")
                quiet["selection_role"] = "random_control"
                out.append(quiet)
    if not out:
        return pd.DataFrame(columns=list(a.columns) + ["selection_role"])
    result = pd.concat(out, ignore_index=True)
    return result.drop_duplicates(["session_date", "ticker"], keep="first").sort_values(
        ["session_date", "selection_role", "signal_activity_score", "ticker"],
        ascending=[True, True, False, True],
    ).reset_index(drop=True)
