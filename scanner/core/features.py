from __future__ import annotations

from datetime import time
from typing import Any, Mapping

import numpy as np
import pandas as pd

ET = "America/New_York"


def prepare_intraday_bars(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if out.empty:
        if "timestamp_et" not in out.columns:
            out["timestamp_et"] = pd.Series(dtype="datetime64[ns, America/New_York]")
        if "session_date" not in out.columns:
            out["session_date"] = pd.Series(dtype="object")
        return out
    if "timestamp_et" in out.columns:
        ts = pd.to_datetime(out["timestamp_et"], utc=True, errors="coerce")
    elif "timestamp" in out.columns:
        ts = pd.to_datetime(out["timestamp"], utc=True, errors="coerce")
    else:
        raise ValueError("bars must contain timestamp or timestamp_et")
    out["timestamp_et"] = ts.dt.tz_convert(ET)
    out["session_date"] = out["timestamp_et"].dt.date
    if "symbol" not in out.columns:
        out["symbol"] = "UNKNOWN"
    for column in ("open", "high", "low", "close", "volume", "vwap"):
        if column in out.columns:
            out[column] = pd.to_numeric(out[column], errors="coerce")
    return out.sort_values(["symbol", "timestamp_et"]).reset_index(drop=True)


def opening_range(df: pd.DataFrame, minutes: int = 5) -> dict[str, Any]:
    if minutes <= 0:
        raise ValueError("minutes must be positive")
    bars = prepare_intraday_bars(df)
    if bars.empty:
        return {"high": np.nan, "low": np.nan, "volume": 0.0, "dollar_turnover": 0.0, "bars": 0}
    start = time(9, 30)
    end_ts = pd.Timestamp.combine(pd.Timestamp("2000-01-01").date(), start) + pd.Timedelta(minutes=minutes)
    end = end_ts.time()
    clock = bars["timestamp_et"].dt.time
    window = bars[(clock >= start) & (clock < end)].copy()
    if window.empty:
        return {"high": np.nan, "low": np.nan, "volume": 0.0, "dollar_turnover": 0.0, "bars": 0}
    volume = pd.to_numeric(window.get("volume", 0.0), errors="coerce").fillna(0.0)
    price = pd.to_numeric(window.get("vwap", window.get("close")), errors="coerce")
    if "close" in window.columns:
        price = price.fillna(pd.to_numeric(window["close"], errors="coerce"))
    return {
        "high": float(pd.to_numeric(window["high"], errors="coerce").max()),
        "low": float(pd.to_numeric(window["low"], errors="coerce").min()),
        "volume": float(volume.sum()),
        "dollar_turnover": float((price.fillna(0.0) * volume).sum()),
        "bars": int(len(window)),
    }


def rolling_prior_volume_median(df: pd.DataFrame, lookback_bars: int = 5) -> pd.Series:
    if lookback_bars <= 0:
        raise ValueError("lookback_bars must be positive")
    volume = pd.to_numeric(df["volume"], errors="coerce")
    return volume.shift(1).rolling(lookback_bars, min_periods=1).median()


def attach_session_vwap(df: pd.DataFrame) -> pd.DataFrame:
    out = prepare_intraday_bars(df)
    if out.empty:
        out["session_vwap"] = pd.Series(dtype="float64")
        return out
    volume = pd.to_numeric(out.get("volume", 0.0), errors="coerce").fillna(0.0).clip(lower=0.0)
    typical = (
        pd.to_numeric(out["high"], errors="coerce")
        + pd.to_numeric(out["low"], errors="coerce")
        + pd.to_numeric(out["close"], errors="coerce")
    ) / 3.0
    if "vwap" in out.columns:
        bar_price = pd.to_numeric(out["vwap"], errors="coerce").where(lambda s: s > 0).fillna(typical)
    else:
        bar_price = typical
    out["_pv"] = bar_price * volume
    out["_vol"] = volume
    groups = [out["symbol"], out["session_date"]]
    out["_cum_pv"] = out["_pv"].groupby(groups, sort=False).cumsum()
    out["_cum_vol"] = out["_vol"].groupby(groups, sort=False).cumsum()
    out["session_vwap"] = out["_cum_pv"] / out["_cum_vol"].replace(0, np.nan)
    return out.drop(columns=["_pv", "_vol", "_cum_pv", "_cum_vol"])


def close_location_value(row: Mapping[str, Any]) -> float:
    high = float(row["high"])
    low = float(row["low"])
    close = float(row["close"])
    width = high - low
    if not np.isfinite(width) or width <= 0:
        return 0.5
    return float(np.clip((close - low) / width, 0.0, 1.0))


def bucket_gap(value: Any) -> str:
    try:
        gap = abs(float(value))
    except (TypeError, ValueError):
        return "UNKNOWN"
    if not np.isfinite(gap):
        return "UNKNOWN"
    if gap < 0.05:
        return "<5%"
    if gap < 0.08:
        return "5-8%"
    if gap < 0.10:
        return "8-10%"
    if gap < 0.15:
        return "10-15%"
    if gap < 0.20:
        return "15-20%"
    return "20%+"


def bucket_rvol(value: Any) -> str:
    try:
        rvol = float(value)
    except (TypeError, ValueError):
        return "UNKNOWN"
    if not np.isfinite(rvol):
        return "UNKNOWN"
    if rvol < 3:
        return "<3x"
    if rvol < 5:
        return "3-5x"
    if rvol < 10:
        return "5-10x"
    return "10x+"


def bucket_float(value: Any) -> str:
    try:
        shares = float(value)
    except (TypeError, ValueError):
        return "UNKNOWN"
    if not np.isfinite(shares) or shares <= 0:
        return "UNKNOWN"
    if shares < 5_000_000:
        return "<5M"
    if shares < 10_000_000:
        return "5-10M"
    if shares < 20_000_000:
        return "10-20M"
    if shares < 50_000_000:
        return "20-50M"
    return "50M+"


def bucket_time_of_day(value: Any) -> str:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize(ET)
    else:
        ts = ts.tz_convert(ET)
    clock = ts.time()
    if time(4, 0) <= clock < time(9, 30):
        return "04:00-09:30"
    if time(9, 30) <= clock < time(10, 30):
        return "09:30-10:30"
    if time(10, 30) <= clock < time(15, 0):
        return "10:30-15:00"
    if time(15, 0) <= clock < time(16, 0):
        return "15:00-16:00"
    if time(16, 0) <= clock < time(20, 0):
        return "16:00-20:00"
    return "OUTSIDE"
