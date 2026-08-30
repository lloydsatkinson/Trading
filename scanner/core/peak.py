from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd

ET = "America/New_York"


@dataclass(frozen=True)
class PeakResult:
    peak_timestamp: pd.Timestamp | None
    peak_price: float
    peak_return_pct: float
    minutes_to_peak: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _et_timestamp(value: Any) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize(ET)
    return ts.tz_convert(ET)


def _prepare_bars(bars: pd.DataFrame) -> pd.DataFrame:
    x = bars.copy()
    if x.empty:
        return x
    if "timestamp_et" in x.columns:
        ts = pd.to_datetime(x["timestamp_et"], utc=True, errors="coerce")
    elif "timestamp" in x.columns:
        ts = pd.to_datetime(x["timestamp"], utc=True, errors="coerce")
    else:
        raise ValueError("bars must contain timestamp or timestamp_et")
    x["timestamp_et"] = ts.dt.tz_convert(ET)
    for col in ("high", "low"):
        x[col] = pd.to_numeric(x[col], errors="coerce")
    return x.dropna(subset=["timestamp_et"]).sort_values("timestamp_et").reset_index(drop=True)


def analyze_same_session_peak(
    bars: pd.DataFrame,
    entry_price: float,
    entry_timestamp: Any,
    direction: str,
    session_end: str = "16:00",
) -> PeakResult:
    direction = str(direction).upper()
    if direction not in {"LONG", "SHORT"}:
        raise ValueError("direction must be LONG or SHORT")
    entry = float(entry_price)
    if bars.empty or not np.isfinite(entry) or entry <= 0:
        return PeakResult(None, np.nan, np.nan, np.nan)

    x = _prepare_bars(bars)
    entry_ts = _et_timestamp(entry_timestamp)
    hour, minute = [int(part) for part in session_end.split(":", 1)]
    end_ts = entry_ts.normalize() + pd.Timedelta(hours=hour, minutes=minute)
    x = x[(x["timestamp_et"] >= entry_ts) & (x["timestamp_et"] < end_ts)].copy()
    if x.empty:
        return PeakResult(None, np.nan, np.nan, np.nan)

    series = x["high"] if direction == "LONG" else x["low"]
    series = pd.to_numeric(series, errors="coerce")
    if series.dropna().empty:
        return PeakResult(None, np.nan, np.nan, np.nan)
    idx = series.idxmax() if direction == "LONG" else series.idxmin()
    peak_price = float(series.loc[idx])
    peak_ts = x.loc[idx, "timestamp_et"]
    peak_return = (peak_price - entry) / entry if direction == "LONG" else (entry - peak_price) / entry
    minutes = float((peak_ts - entry_ts).total_seconds() / 60.0)
    return PeakResult(peak_ts, peak_price, float(peak_return), minutes)
