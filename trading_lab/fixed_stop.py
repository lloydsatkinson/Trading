from __future__ import annotations

import pandas as pd


def simulate_fixed_stop(
    bars: pd.DataFrame,
    *,
    side: str,
    entry: float,
    target: float,
    stop_pct: float,
    slip_bps: float = 20.0,
) -> dict:
    """Replay an existing entry/target while replacing only the stop distance."""
    side = side.upper()
    if side not in {"LONG", "SHORT"}:
        raise ValueError("side must be LONG or SHORT")
    if not 0 < stop_pct < 1:
        raise ValueError("stop_pct must be between 0 and 1")
    if bars.empty:
        raise ValueError("bars must not be empty")

    x = bars.copy()
    for c in ("open", "high", "low", "close"):
        x[c] = pd.to_numeric(x[c], errors="coerce")
    x = x.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)
    if x.empty:
        raise ValueError("bars contain no valid OHLC rows")

    q = slip_bps / 10000.0
    stop = entry * (1.0 - stop_pct) if side == "LONG" else entry * (1.0 + stop_pct)
    exit_px = None
    reason = "TIME"
    exit_i = len(x) - 1

    for i, row in x.iterrows():
        lo = float(row.low)
        hi = float(row.high)
        if side == "LONG":
            if lo <= stop:
                exit_px = stop * (1.0 - q)
                reason = "STOP"
                exit_i = i
                break
            if hi >= target:
                exit_px = target * (1.0 - q)
                reason = "TARGET"
                exit_i = i
                break
        else:
            if hi >= stop:
                exit_px = stop * (1.0 + q)
                reason = "STOP"
                exit_i = i
                break
            if lo <= target:
                exit_px = target * (1.0 + q)
                reason = "TARGET"
                exit_i = i
                break

    if exit_px is None:
        raw = float(x.close.iloc[-1])
        exit_px = raw * (1.0 - q if side == "LONG" else 1.0 + q)

    ret = (exit_px - entry) / entry if side == "LONG" else (entry - exit_px) / entry
    ts = x.timestamp.iloc[exit_i] if "timestamp" in x.columns else exit_i
    return {
        "stop": float(stop),
        "target": float(target),
        "exit": float(exit_px),
        "exit_ts": str(ts),
        "reason": reason,
        "return_pct": float(ret),
    }
