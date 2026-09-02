from __future__ import annotations

from math import isfinite
from typing import Any, Iterable

import numpy as np
import pandas as pd

ET = "America/New_York"


def retained_gain_ratio(impulse_start: Any, impulse_high: Any, reference_price: Any) -> float:
    try:
        start = float(impulse_start)
        high = float(impulse_high)
        reference = float(reference_price)
    except (TypeError, ValueError):
        return np.nan
    if not all(isfinite(value) for value in (start, high, reference)) or high <= start:
        return np.nan
    return (reference - start) / (high - start)


def _et_timestamp(value: Any) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize(ET) if ts.tzinfo is None else ts.tz_convert(ET)


def retained_gain_checkpoint_values(
    bars: pd.DataFrame,
    impulse_timestamp: Any,
    impulse_start_price: Any,
    impulse_high_price: Any,
    checkpoints_minutes: Iterable[int] = (10, 20, 30, 60, 90),
) -> dict[str, float]:
    """Return retained-gain ratios at fixed timestamps without future leakage.

    Each checkpoint only inspects bars at or before its own timestamp. The last
    available close at/before the checkpoint is used, so a later spike or selloff
    can never revise an earlier retained-gain observation.
    """
    result = {f"retained_gain_{int(minutes)}m": np.nan for minutes in checkpoints_minutes}
    if bars is None or bars.empty:
        return result

    x = bars.copy()
    timestamp_column = "timestamp_et" if "timestamp_et" in x.columns else "timestamp" if "timestamp" in x.columns else None
    if timestamp_column is None or "close" not in x.columns:
        return result

    ts = pd.to_datetime(x[timestamp_column], utc=True, errors="coerce")
    x["_timestamp_et"] = ts.dt.tz_convert(ET)
    x["_close"] = pd.to_numeric(x["close"], errors="coerce")
    x = x.dropna(subset=["_timestamp_et", "_close"]).sort_values("_timestamp_et")
    if x.empty:
        return result

    impulse_ts = _et_timestamp(impulse_timestamp)
    for minutes in checkpoints_minutes:
        minutes = int(minutes)
        checkpoint_ts = impulse_ts + pd.Timedelta(minutes=minutes)
        observed = x[(x["_timestamp_et"] >= impulse_ts) & (x["_timestamp_et"] <= checkpoint_ts)]
        if observed.empty:
            continue
        reference_price = float(observed.iloc[-1]["_close"])
        result[f"retained_gain_{minutes}m"] = retained_gain_ratio(
            impulse_start_price,
            impulse_high_price,
            reference_price,
        )
    return result


def bucket_retained_gain(value: Any) -> str:
    try:
        ratio = float(value)
    except (TypeError, ValueError):
        return "UNKNOWN"
    if not isfinite(ratio):
        return "UNKNOWN"
    if ratio < 0.40:
        return "LT_40"
    if ratio < 0.50:
        return "40_50"
    if ratio < 0.65:
        return "50_65"
    if ratio < 0.80:
        return "65_80"
    return "GE_80"
