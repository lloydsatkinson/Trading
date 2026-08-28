from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np
import pandas as pd

NY = "America/New_York"


@dataclass(frozen=True)
class ExecutionRule:
    stop_pct: float
    target_pct: float
    max_hold_minutes: int
    slippage_bps: float = 20.0


@dataclass(frozen=True)
class ExecutionTrade:
    side: str
    signal_ts: str
    entry_ts: str
    exit_ts: str
    entry_price: float
    exit_price: float
    stop_price: float
    target_price: float
    return_pct: float
    return_r: float
    exit_reason: str


def _prepared(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"timestamp", "open", "high", "low", "close", "volume"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"missing {sorted(missing)}")
    x = frame.copy()
    x["timestamp"] = pd.to_datetime(x["timestamp"], utc=True, errors="coerce")
    x = x.dropna(subset=["timestamp"]).sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    for c in ("open", "high", "low", "close", "volume"):
        x[c] = pd.to_numeric(x[c], errors="coerce")
    x = x.dropna(subset=["open", "high", "low", "close"])
    z = x["timestamp"].dt.tz_convert(NY)
    x["session_date"] = z.dt.date.astype(str)
    x["minute"] = z.dt.hour * 60 + z.dt.minute
    return x


def _to_utc(ts) -> pd.Timestamp:
    z = pd.Timestamp(ts)
    if z.tzinfo is None:
        z = z.tz_localize(NY)
    return z.tz_convert("UTC")


def _clock_minute(text: str) -> int:
    h, m = (int(v) for v in text.split(":", 1))
    return h * 60 + m


def _historical_elapsed_volume(history: pd.DataFrame, freeze_minute: int, current_date: str) -> float:
    if history is None or history.empty or freeze_minute < 570:
        return np.nan
    h = _prepared(history)
    h = h[(h["session_date"] < current_date) & (h["minute"] >= 570) & (h["minute"] <= freeze_minute)]
    if h.empty:
        return np.nan
    totals = h.groupby("session_date", sort=True)["volume"].sum(min_count=1)
    totals = totals[totals > 0]
    return float(totals.mean()) if not totals.empty else np.nan


def build_snapshots(
    day_bars: pd.DataFrame,
    history_open_bars: pd.DataFrame | None = None,
    freeze_times: Sequence[str] = ("09:25", "09:29", "09:31", "09:32", "09:33", "09:34", "09:35"),
) -> pd.DataFrame:
    """Build no-lookahead signal-time snapshots for one ticker/session.

    A row is computed from bars whose timestamp minute is at or before the requested
    freeze minute. Historical opening RVOL uses the exact same 09:30-to-freeze
    elapsed window on prior sessions.
    """
    x = _prepared(day_bars)
    if x.empty:
        return pd.DataFrame()
    dates = x["session_date"].unique()
    if len(dates) != 1:
        raise ValueError("day_bars must contain exactly one ET session date")
    session_date = str(dates[0])
    ticker = str(x["ticker"].iloc[0]).upper() if "ticker" in x.columns else "UNKNOWN"
    if "previous_close" in x.columns:
        prev = pd.to_numeric(x["previous_close"], errors="coerce").dropna()
        previous_close = float(prev.iloc[0]) if not prev.empty else np.nan
    else:
        previous_close = np.nan

    rows: list[dict] = []
    for freeze in freeze_times:
        fm = _clock_minute(freeze)
        seen = x[x["minute"] <= fm]
        if seen.empty:
            continue
        last = seen.iloc[-1]
        snapshot_price = float(last["close"])
        pm = seen[(seen["minute"] >= 240) & (seen["minute"] < 570)]
        reg = seen[(seen["minute"] >= 570) & (seen["minute"] < 960)]

        pm_high = float(pm["high"].max()) if not pm.empty else np.nan
        pm_low = float(pm["low"].min()) if not pm.empty else np.nan
        pm_volume = float(pm["volume"].fillna(0).sum()) if not pm.empty else 0.0
        pm_dollar_volume = float((pm["close"] * pm["volume"].fillna(0)).sum()) if not pm.empty else 0.0
        pm_last = float(pm["close"].iloc[-1]) if not pm.empty else np.nan

        open_cum_volume = float(reg["volume"].fillna(0).sum()) if not reg.empty else 0.0
        hist_mean = _historical_elapsed_volume(history_open_bars, fm, session_date) if history_open_bars is not None else np.nan
        open_rvol = open_cum_volume / hist_mean if np.isfinite(hist_mean) and hist_mean > 0 else np.nan

        hod = float(reg["high"].max()) if not reg.empty else (pm_high if np.isfinite(pm_high) else snapshot_price)
        lod = float(reg["low"].min()) if not reg.empty else (pm_low if np.isfinite(pm_low) else snapshot_price)
        if not reg.empty and float(reg["volume"].fillna(0).sum()) > 0:
            typical = (reg["high"] + reg["low"] + reg["close"]) / 3.0
            vwap = float((typical * reg["volume"].fillna(0)).sum() / reg["volume"].fillna(0).sum())
        else:
            vwap = np.nan

        if not reg.empty:
            current_volume = float(reg["volume"].iloc[-1] or 0)
            prior_volumes = reg["volume"].iloc[:-1].dropna().tail(3)
            volume_base = float(prior_volumes.median()) if not prior_volumes.empty else np.nan
            volume_accel = current_volume / volume_base if np.isfinite(volume_base) and volume_base > 0 else np.nan
            recent = reg.tail(2)
            earlier = reg.iloc[max(0, len(reg) - 5): max(0, len(reg) - 2)]
            recent_range = float(recent["high"].max() - recent["low"].min()) if not recent.empty else np.nan
            earlier_range = float(earlier["high"].max() - earlier["low"].min()) if not earlier.empty else np.nan
            contraction_ratio = recent_range / earlier_range if np.isfinite(earlier_range) and earlier_range > 0 else np.nan
        else:
            volume_accel = np.nan
            contraction_ratio = np.nan

        hod_gain = hod / previous_close - 1.0 if np.isfinite(previous_close) and previous_close > 0 else np.nan
        snapshot_gain = snapshot_price / previous_close - 1.0 if np.isfinite(previous_close) and previous_close > 0 else np.nan
        retained = snapshot_gain / hod_gain if np.isfinite(hod_gain) and hod_gain > 0 else np.nan
        pullback = 1.0 - snapshot_price / hod if hod > 0 else np.nan
        clv_den = hod - lod
        close_location = (snapshot_price - lod) / clv_den if clv_den > 0 else np.nan

        rows.append({
            "ticker": ticker,
            "session_date": session_date,
            "freeze_time": freeze,
            "freeze_minute": fm,
            "signal_ts": last["timestamp"].isoformat(),
            "snapshot_price": snapshot_price,
            "previous_close": previous_close,
            "pm_last": pm_last,
            "pm_high": pm_high,
            "pm_low": pm_low,
            "pm_volume": pm_volume,
            "pm_dollar_volume": pm_dollar_volume,
            "pm_gap_pct": pm_last / previous_close - 1.0 if np.isfinite(pm_last) and np.isfinite(previous_close) and previous_close > 0 else np.nan,
            "pm_high_distance_pct": snapshot_price / pm_high - 1.0 if np.isfinite(pm_high) and pm_high > 0 else np.nan,
            "open_cum_volume": open_cum_volume,
            "open_rvol": open_rvol,
            "impulse_pct": snapshot_gain,
            "hod_extension_pct": hod_gain,
            "pullback_from_hod_pct": pullback,
            "gain_retention": retained,
            "vwap": vwap,
            "vwap_distance_pct": snapshot_price / vwap - 1.0 if np.isfinite(vwap) and vwap > 0 else np.nan,
            "volume_accel": volume_accel,
            "contraction_ratio": contraction_ratio,
            "close_location": close_location,
        })

    out = pd.DataFrame(rows)
    if not out.empty:
        out["rvol_slope"] = out["open_rvol"].diff()
    return out


def label_snapshot(
    day_bars: pd.DataFrame,
    signal_ts,
    thresholds: Iterable[float] = (0.10, 0.20, 0.30, 0.50),
) -> dict:
    x = _prepared(day_bars)
    sig = _to_utc(signal_ts)
    future = x[x["timestamp"] > sig].copy()
    if future.empty:
        return {}
    entry = float(future.iloc[0]["open"])
    if entry <= 0:
        return {}
    max_high = float(future["high"].max())
    min_low = float(future["low"].min())
    long_mfe = max(0.0, max_high / entry - 1.0)
    long_mae = max(0.0, 1.0 - min_low / entry)
    short_mfe = max(0.0, 1.0 - min_low / entry)
    short_mae = max(0.0, max_high / entry - 1.0)
    result: dict = {
        "entry_ts": future.iloc[0]["timestamp"].isoformat(),
        "entry_price": entry,
        "long_mfe_pct": long_mfe,
        "long_mae_pct": long_mae,
        "short_mfe_pct": short_mfe,
        "short_mae_pct": short_mae,
    }
    entry_ts = future.iloc[0]["timestamp"]
    for threshold in thresholds:
        pct = int(round(float(threshold) * 100))
        long_hit = future[future["high"] >= entry * (1.0 + threshold)]
        short_hit = future[future["low"] <= entry * (1.0 - threshold)]
        result[f"long_reach_{pct}"] = bool(not long_hit.empty)
        result[f"short_reach_{pct}"] = bool(not short_hit.empty)
        result[f"long_time_to_{pct}_min"] = (
            float((long_hit.iloc[0]["timestamp"] - entry_ts).total_seconds() / 60.0) if not long_hit.empty else np.nan
        )
        result[f"short_time_to_{pct}_min"] = (
            float((short_hit.iloc[0]["timestamp"] - entry_ts).total_seconds() / 60.0) if not short_hit.empty else np.nan
        )
    return result


def simulate_snapshot_trade(
    day_bars: pd.DataFrame,
    signal_ts,
    side: str,
    rule: ExecutionRule,
) -> ExecutionTrade | None:
    side = str(side).upper()
    if side not in {"LONG", "SHORT"}:
        raise ValueError("side must be LONG or SHORT")
    if not (0 < rule.stop_pct < 1 and 0 < rule.target_pct < 1 and rule.max_hold_minutes > 0):
        raise ValueError("invalid execution rule")
    x = _prepared(day_bars)
    sig = _to_utc(signal_ts)
    future = x[x["timestamp"] > sig].copy().reset_index(drop=True)
    if future.empty:
        return None
    q = float(rule.slippage_bps) / 10000.0
    raw_entry = float(future.iloc[0]["open"])
    entry = raw_entry * (1.0 + q if side == "LONG" else 1.0 - q)
    if entry <= 0:
        return None
    if side == "LONG":
        stop = entry * (1.0 - rule.stop_pct)
        target = entry * (1.0 + rule.target_pct)
    else:
        stop = entry * (1.0 + rule.stop_pct)
        target = entry * (1.0 - rule.target_pct)

    entry_ts = future.iloc[0]["timestamp"]
    last_row = future.iloc[0]
    exit_price = None
    exit_reason = None
    exit_ts = entry_ts
    previous_ts = entry_ts

    for idx, row in future.iterrows():
        ts = row["timestamp"]
        elapsed = (ts - entry_ts).total_seconds() / 60.0
        if elapsed > rule.max_hold_minutes:
            break
        gap = idx > 0 and (ts - previous_ts).total_seconds() > 90
        op, lo, hi = float(row["open"]), float(row["low"]), float(row["high"])

        if gap:
            if side == "LONG" and op < stop:
                exit_price = op * (1.0 - q)
                exit_reason = "GAP_STOP"
            elif side == "SHORT" and op > stop:
                exit_price = op * (1.0 + q)
                exit_reason = "GAP_STOP"
            if exit_reason:
                exit_ts = ts
                break

        if side == "LONG":
            stop_hit = lo <= stop
            target_hit = hi >= target
            if stop_hit:
                exit_price = stop * (1.0 - q)
                exit_reason = "STOP_SAME_BAR" if target_hit else "STOP"
            elif target_hit:
                exit_price = target * (1.0 - q)
                exit_reason = "TARGET"
        else:
            stop_hit = hi >= stop
            target_hit = lo <= target
            if stop_hit:
                exit_price = stop * (1.0 + q)
                exit_reason = "STOP_SAME_BAR" if target_hit else "STOP"
            elif target_hit:
                exit_price = target * (1.0 + q)
                exit_reason = "TARGET"

        last_row = row
        previous_ts = ts
        if exit_reason:
            exit_ts = ts
            break

    if exit_price is None:
        raw_exit = float(last_row["close"])
        exit_price = raw_exit * (1.0 - q if side == "LONG" else 1.0 + q)
        exit_reason = "TIME"
        exit_ts = last_row["timestamp"]

    ret = (exit_price - entry) / entry if side == "LONG" else (entry - exit_price) / entry
    risk_pct = rule.stop_pct
    return ExecutionTrade(
        side=side,
        signal_ts=sig.isoformat(),
        entry_ts=entry_ts.isoformat(),
        exit_ts=exit_ts.isoformat(),
        entry_price=float(entry),
        exit_price=float(exit_price),
        stop_price=float(stop),
        target_price=float(target),
        return_pct=float(ret),
        return_r=float(ret / risk_pct),
        exit_reason=str(exit_reason),
    )
