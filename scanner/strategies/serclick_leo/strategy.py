from __future__ import annotations

from math import isfinite
from typing import Any

import pandas as pd

from scanner.core.features import bucket_float, bucket_gap, bucket_rvol, bucket_time_of_day
from scanner.core.models import SignalRecord, market_cap_bucket


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def serclick_variant(population: str, window: str) -> str:
    if window == "09:30-10:30":
        return "MORNING_OBSERVATION"
    if population == "BOTH" and window == "10:30-15:00":
        return "LEO_BOTH_MIDDAY"
    if population == "BOTH" and window == "16:00-20:00":
        return "LEO_BOTH_AH"
    return "SERCLICK_CONTROL"


# Preserve the prior private name for internal/backward compatibility.
_variant = serclick_variant


def adapt_serclick_ignitions(ignitions: pd.DataFrame) -> pd.DataFrame:
    if ignitions.empty:
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    for _, source in ignitions.iterrows():
        base = source.to_dict()
        population = str(base.get("population") or "UNKNOWN")
        window = str(base.get("ignition_window") or "UNKNOWN")
        signal_timestamp = base.get("timestamp_et", base.get("timestamp"))
        entry_timestamp = base.get("entry_timestamp")
        raw_value = base.get("entry_price_raw", base.get("entry_raw_open"))
        if raw_value is None:
            raise ValueError("SerClick ignition missing entry_price_raw/entry_raw_open")
        raw_entry = float(raw_value)
        slipped_entry = float(base["entry_price_slipped"])
        cap = _number(base.get("market_cap"))
        float_shares = _number(base.get("float_shares"))
        source_cap_bucket = str(base.get("market_cap_bucket") or "UNKNOWN")
        cap_bucket = source_cap_bucket if source_cap_bucket != "UNKNOWN" else market_cap_bucket(cap)
        reference_price = _number(base.get("ignition_price"))
        if reference_price is None:
            reference_price = _number(base.get("reference_price"))
        if reference_price is None:
            reference_price = raw_entry
        record = SignalRecord(
            strategy_id="SERCLICK_LEO",
            variant_id=serclick_variant(population, window),
            symbol=str(base.get("symbol") or "UNKNOWN"),
            date=str(base.get("date") or "UNKNOWN"),
            direction="LONG",
            signal_timestamp=signal_timestamp,
            reference_price=float(reference_price),
            entry_timestamp=entry_timestamp,
            entry_price_raw=raw_entry,
            entry_price_slipped=slipped_entry,
            stop_reference=_number(base.get("stop_reference")),
            market_cap=cap,
            market_cap_bucket=cap_bucket,
            float_shares=float_shares,
            float_bucket=bucket_float(float_shares),
            gap_bucket=bucket_gap(base.get("pm_gap_pct")),
            rvol_bucket=bucket_rvol(base.get("opening_rvol")),
            time_of_day_bucket=bucket_time_of_day(signal_timestamp) if signal_timestamp is not None else "UNKNOWN",
            catalyst_class=str(base.get("catalyst_class") or "UNKNOWN"),
            borrow_status="NOT_APPLICABLE",
            setup_metadata={"population": population, "ignition_window": window},
        ).to_dict()
        rows.append({**base, **record, "split": str(base.get("split") or "forward"), "population": population, "ignition_window": window})
    return pd.DataFrame(rows)
