from __future__ import annotations

from math import isfinite
from typing import Any

import numpy as np
import pandas as pd

from scanner.core.features import (
    attach_session_vwap,
    bucket_float,
    bucket_gap,
    bucket_rvol,
    bucket_time_of_day,
    close_location_value,
    rolling_prior_volume_median,
)
from scanner.core.models import (
    SignalRecord,
    TriggerDecision,
    market_cap_bucket,
    market_cap_in_primary_universe,
)
from scanner.core.replay import apply_entry_slippage
from .config import VWAPConfig


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def _candidate_ok(context: dict[str, Any], cfg: VWAPConfig) -> bool:
    prior_close = _number(context.get("prior_close"))
    if prior_close is None or not (cfg.min_price <= prior_close <= cfg.max_price):
        return False
    cap = _number(context.get("market_cap"))
    if cap is not None and not market_cap_in_primary_universe(cap):
        return False
    gap = _number(context.get("pm_gap_pct"))
    turnover = _number(context.get("pm_dollar_turnover"))
    rvol = _number(context.get("opening_rvol"))
    return bool(
        gap is not None and gap >= cfg.min_gap_pct
        and turnover is not None and turnover >= cfg.min_pm_dollar_turnover
        and rvol is not None and rvol >= cfg.min_rvol
    )


def _signal(
    context: dict[str, Any],
    variant_id: str,
    direction: str,
    signal_row: pd.Series,
    entry_row: pd.Series,
    stop_reference: float,
    cfg: VWAPConfig,
    setup: dict[str, Any],
) -> dict[str, Any]:
    cap = _number(context.get("market_cap"))
    float_shares = _number(context.get("float_shares"))
    raw_entry = float(entry_row["open"])
    record = SignalRecord(
        strategy_id="VWAP",
        variant_id=variant_id,
        symbol=str(context.get("symbol") or signal_row.get("symbol") or "UNKNOWN"),
        date=str(context.get("date") or signal_row["session_date"]),
        direction=direction,
        signal_timestamp=signal_row["timestamp_et"],
        reference_price=float(signal_row["close"]),
        entry_timestamp=entry_row["timestamp_et"],
        entry_price_raw=raw_entry,
        entry_price_slipped=apply_entry_slippage(raw_entry, direction, cfg.slippage_bps),
        stop_reference=float(stop_reference),
        market_cap=cap,
        market_cap_bucket=market_cap_bucket(cap),
        float_shares=float_shares,
        float_bucket=bucket_float(float_shares),
        gap_bucket=bucket_gap(context.get("pm_gap_pct")),
        rvol_bucket=bucket_rvol(context.get("opening_rvol")),
        time_of_day_bucket=bucket_time_of_day(signal_row["timestamp_et"]),
        catalyst_class=str(context.get("catalyst_class") or "UNKNOWN"),
        borrow_status=str(context.get("borrow_status") or "UNKNOWN"),
        setup_metadata=setup,
    ).to_dict()
    record["split"] = str(context.get("split") or "forward")
    record["pm_gap_pct"] = context.get("pm_gap_pct")
    record["pm_dollar_turnover"] = context.get("pm_dollar_turnover")
    record["opening_rvol"] = context.get("opening_rvol")
    return record


def detect_vwap_triggers(
    bars: pd.DataFrame,
    context: dict[str, Any],
    cfg: VWAPConfig | None = None,
) -> list[TriggerDecision]:
    """Detect VWAP momentum triggers from the supplied completed-bar prefix only."""
    cfg = cfg or VWAPConfig()
    if bars.empty or not _candidate_ok(context, cfg):
        return []
    prior_close = float(context["prior_close"])
    x = attach_session_vwap(bars)
    if x.empty:
        return []
    x["prior_volume_median"] = rolling_prior_volume_median(x, cfg.volume_lookback_bars)
    x["volume_ratio"] = pd.to_numeric(x["volume"], errors="coerce") / x["prior_volume_median"].replace(0, np.nan)
    x["clv"] = x.apply(close_location_value, axis=1)
    x["running_high"] = pd.to_numeric(x["high"], errors="coerce").cummax()
    x["impulse_pct"] = x["running_high"] / prior_close - 1.0

    impulse_candidates = x.index[x["impulse_pct"] >= cfg.min_impulse_pct].tolist()
    if not impulse_candidates:
        return []
    impulse_idx = impulse_candidates[0]
    decisions: list[TriggerDecision] = []

    touch_idx = None
    peak_price = float(x.loc[:impulse_idx, "high"].max())
    pullback_low = None
    for idx in x.index:
        if idx <= impulse_idx:
            continue
        peak_price = max(peak_price, float(x.loc[idx, "high"]))
        vwap = _number(x.loc[idx, "session_vwap"])
        if vwap is None:
            continue
        if float(x.loc[idx, "low"]) <= vwap:
            touch_idx = idx
            pullback_low = float(x.loc[idx, "low"])
            break

    if touch_idx is not None and pullback_low is not None and peak_price > prior_close:
        retained_gain = (pullback_low - prior_close) / (peak_price - prior_close)
        if retained_gain >= cfg.min_retained_gain:
            for idx in x.index:
                if idx <= touch_idx:
                    continue
                row = x.loc[idx]
                vwap = _number(row["session_vwap"])
                ratio = _number(row["volume_ratio"])
                if vwap is None or ratio is None:
                    continue
                if (
                    float(row["close"]) > vwap
                    and ratio >= cfg.min_reclaim_volume_ratio
                    and float(row["clv"]) >= cfg.min_clv
                ):
                    structural_low = float(x.loc[impulse_idx:idx, "low"].min())
                    vwap_5_back = _number(x.loc[max(0, idx - 5), "session_vwap"])
                    rising_vwap = bool(vwap_5_back is not None and vwap > vwap_5_back)
                    decisions.append(
                        TriggerDecision(
                            variant_id="VWAP_LONG_RECLAIM",
                            direction="LONG",
                            signal_timestamp=row["timestamp_et"],
                            reference_price=float(row["close"]),
                            stop_reference=structural_low,
                            setup_metadata={
                                "impulse_pct": float(x.loc[impulse_idx:idx, "impulse_pct"].max()),
                                "peak_price": peak_price,
                                "retained_gain": retained_gain,
                                "touch_timestamp": x.loc[touch_idx, "timestamp_et"],
                                "volume_ratio": ratio,
                                "clv": float(row["clv"]),
                                "rising_vwap": rising_vwap,
                            },
                        )
                    )
                    break

    loss_idx = None
    for idx in x.index:
        if idx <= impulse_idx:
            continue
        vwap = _number(x.loc[idx, "session_vwap"])
        if vwap is not None and float(x.loc[idx, "close"]) < vwap:
            loss_idx = idx
            break

    if loss_idx is not None:
        rejection_idx = None
        for idx in x.index:
            if idx <= loss_idx:
                continue
            vwap = _number(x.loc[idx, "session_vwap"])
            if vwap is None:
                continue
            if float(x.loc[idx, "high"]) >= vwap and float(x.loc[idx, "close"]) < vwap:
                rejection_idx = idx
                break
        if rejection_idx is not None:
            rejection_low = float(x.loc[rejection_idx, "low"])
            rejection_high = float(x.loc[rejection_idx, "high"])
            for idx in x.index:
                if idx <= rejection_idx:
                    continue
                row = x.loc[idx]
                ratio = _number(row["volume_ratio"])
                vwap = _number(row["session_vwap"])
                if ratio is None or vwap is None:
                    continue
                if (
                    float(row["low"]) < rejection_low
                    and float(row["close"]) < rejection_low
                    and float(row["close"]) < vwap
                    and ratio >= cfg.min_reclaim_volume_ratio
                    and float(row["clv"]) <= (1.0 - cfg.min_clv)
                ):
                    decisions.append(
                        TriggerDecision(
                            variant_id="VWAP_SHORT_REJECTION",
                            direction="SHORT",
                            signal_timestamp=row["timestamp_et"],
                            reference_price=float(row["close"]),
                            stop_reference=rejection_high,
                            setup_metadata={
                                "impulse_pct": float(x.loc[impulse_idx:rejection_idx, "impulse_pct"].max()),
                                "vwap_loss_timestamp": x.loc[loss_idx, "timestamp_et"],
                                "rejection_timestamp": x.loc[rejection_idx, "timestamp_et"],
                                "volume_ratio": ratio,
                                "clv": float(row["clv"]),
                            },
                        )
                    )
                    break

    return decisions


def generate_vwap_signals(
    bars: pd.DataFrame,
    context: dict[str, Any],
    cfg: VWAPConfig | None = None,
) -> pd.DataFrame:
    cfg = cfg or VWAPConfig()
    decisions = detect_vwap_triggers(bars, context, cfg)
    if not decisions:
        return pd.DataFrame()

    x = attach_session_vwap(bars)
    rows: list[dict[str, Any]] = []
    for decision in decisions:
        matches = x.index[x["timestamp_et"].eq(pd.Timestamp(decision.signal_timestamp))].tolist()
        if not matches:
            continue
        idx = matches[0]
        next_idx = idx + 1
        if next_idx not in x.index or x.loc[next_idx, "session_date"] != x.loc[idx, "session_date"]:
            continue
        rows.append(
            _signal(
                context,
                decision.variant_id,
                decision.direction,
                x.loc[idx],
                x.loc[next_idx],
                float(decision.stop_reference),
                cfg,
                decision.setup_metadata,
            )
        )
    return pd.DataFrame(rows)
