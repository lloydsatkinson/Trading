from __future__ import annotations

from math import isfinite
from typing import Any

import numpy as np


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
