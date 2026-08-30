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
    opening_range,
    rolling_prior_volume_median,
)
from scanner.core.models import SignalRecord, market_cap_bucket, market_cap_in_primary_universe
from scanner.core.replay import apply_entry_slippage
from .config import ORBConfig


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def _candidate_ok(context: dict[str, Any], cfg: ORBConfig) -> bool:
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
        gap is not None
        and abs(gap) >= cfg.min_gap_pct
        and turnover is not None
        and turnover >= cfg.min_pm_dollar_turnover
        and rvol is not None
        and rvol >= cfg.min_opening_rvol
    )


def _base_signal(
    context: dict[str, Any],
    variant_id: str,
    direction: str,
    signal_row: pd.Series,
    entry_row: pd.Series,
    stop_reference: float,
    cfg: ORBConfig,
    setup: dict[str, Any],
) -> dict[str, Any]:
    cap = _number(context.get("market_cap"))
    float_shares = _number(context.get("float_shares"))
    raw_entry = float(entry_row["open"])
    record = SignalRecord(
        strategy_id="ORB",
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


def generate_orb_signals(
    bars: pd.DataFrame,
    context: dict[str, Any],
    cfg: ORBConfig | None = None,
) -> pd.DataFrame:
    cfg = cfg or ORBConfig()
    if bars.empty or not _candidate_ok(context, cfg):
        return pd.DataFrame()

    x = attach_session_vwap(bars)
    if x.empty:
        return pd.DataFrame()
    locked = opening_range(x, minutes=cfg.opening_range_minutes)
    or_high = _number(locked.get("high"))
    or_low = _number(locked.get("low"))
    if or_high is None or or_low is None:
        return pd.DataFrame()

    x["prior_volume_median"] = rolling_prior_volume_median(x, cfg.volume_lookback_bars)
    x["volume_ratio"] = pd.to_numeric(x["volume"], errors="coerce") / x["prior_volume_median"].replace(0, np.nan)
    x["clv"] = x.apply(close_location_value, axis=1)
    post = x[x["timestamp_et"].dt.time >= pd.Timestamp("09:35").time()].copy()
    gap = float(context["pm_gap_pct"])
    rows: list[dict[str, Any]] = []

    for idx in post.index:
        next_idx = idx + 1
        if next_idx not in x.index or x.loc[next_idx, "session_date"] != x.loc[idx, "session_date"]:
            continue
        row = x.loc[idx]
        entry = x.loc[next_idx]
        ratio = _number(row["volume_ratio"])
        session_vwap = _number(row["session_vwap"])
        if ratio is None or ratio < cfg.min_breakout_volume_ratio or session_vwap is None:
            continue
        if gap >= cfg.min_gap_pct and float(row["close"]) > or_high and float(row["close"]) > session_vwap and float(row["clv"]) >= cfg.min_clv:
            rows.append(_base_signal(
                context, "ORB_LONG_BREAK", "LONG", row, entry, float(row["low"]), cfg,
                {"opening_range_high": or_high, "opening_range_low": or_low, "volume_ratio": ratio, "clv": float(row["clv"])},
            ))
            break

    if gap >= cfg.min_gap_pct:
        break_idx = None
        for idx in post.index:
            row = x.loc[idx]
            ratio = _number(row["volume_ratio"])
            session_vwap = _number(row["session_vwap"])
            if ratio is None or session_vwap is None:
                continue
            if (
                float(row["close"]) > or_high
                and float(row["close"]) > session_vwap
                and ratio >= cfg.min_breakout_volume_ratio
                and float(row["clv"]) >= cfg.min_clv
            ):
                break_idx = idx
                break
        if break_idx is not None:
            retest_idx = None
            retest_low = None
            for idx in post.index:
                if idx <= break_idx:
                    continue
                row = x.loc[idx]
                if (
                    float(row["low"]) <= or_high * (1.0 + cfg.pullback_tolerance_pct)
                    and float(row["close"]) >= or_high * (1.0 - cfg.pullback_tolerance_pct)
                ):
                    retest_idx = idx
                    retest_low = float(row["low"])
                    break
            if retest_idx is not None:
                for idx in post.index:
                    if idx <= retest_idx:
                        continue
                    next_idx = idx + 1
                    if next_idx not in x.index or x.loc[next_idx, "session_date"] != x.loc[idx, "session_date"]:
                        continue
                    row = x.loc[idx]
                    entry = x.loc[next_idx]
                    ratio = _number(row["volume_ratio"])
                    session_vwap = _number(row["session_vwap"])
                    if ratio is None or session_vwap is None:
                        continue
                    if (
                        float(row["close"]) > or_high
                        and float(row["close"]) > session_vwap
                        and ratio >= cfg.min_breakout_volume_ratio
                        and float(row["clv"]) >= cfg.min_clv
                    ):
                        rows.append(_base_signal(
                            context, "ORB_LONG_PULLBACK", "LONG", row, entry, float(retest_low), cfg,
                            {"opening_range_high": or_high, "opening_range_low": or_low, "volume_ratio": ratio, "clv": float(row["clv"]), "break_timestamp": x.loc[break_idx, "timestamp_et"], "retest_timestamp": x.loc[retest_idx, "timestamp_et"]},
                        ))
                        break

        failed_high = None
        failed_idx = None
        for idx in post.index:
            row = x.loc[idx]
            if float(row["high"]) > or_high and float(row["close"]) <= or_high:
                failed_idx = idx
                failed_high = float(row["high"])
                break
        if failed_idx is not None:
            for idx in post.index:
                if idx <= failed_idx:
                    continue
                next_idx = idx + 1
                if next_idx not in x.index or x.loc[next_idx, "session_date"] != x.loc[idx, "session_date"]:
                    continue
                row = x.loc[idx]
                entry = x.loc[next_idx]
                ratio = _number(row["volume_ratio"])
                session_vwap = _number(row["session_vwap"])
                if ratio is None or session_vwap is None:
                    continue
                if (
                    float(row["close"]) < or_low
                    and float(row["close"]) < session_vwap
                    and ratio >= cfg.min_breakout_volume_ratio
                    and float(row["clv"]) <= (1.0 - cfg.min_clv)
                ):
                    rows.append(_base_signal(
                        context, "ORB_SHORT_FAILED_GAP", "SHORT", row, entry, float(failed_high), cfg,
                        {"opening_range_high": or_high, "opening_range_low": or_low, "volume_ratio": ratio, "clv": float(row["clv"]), "failed_attempt_timestamp": x.loc[failed_idx, "timestamp_et"]},
                    ))
                    break

    if gap <= -cfg.min_gap_pct:
        for idx in post.index:
            next_idx = idx + 1
            if next_idx not in x.index or x.loc[next_idx, "session_date"] != x.loc[idx, "session_date"]:
                continue
            row = x.loc[idx]
            entry = x.loc[next_idx]
            ratio = _number(row["volume_ratio"])
            session_vwap = _number(row["session_vwap"])
            if ratio is None or session_vwap is None:
                continue
            if ratio >= cfg.min_breakout_volume_ratio and float(row["close"]) < or_low and float(row["close"]) < session_vwap and float(row["clv"]) <= (1.0 - cfg.min_clv):
                rows.append(_base_signal(
                    context, "ORB_SHORT_NEGATIVE_GAP", "SHORT", row, entry, float(row["high"]), cfg,
                    {"opening_range_high": or_high, "opening_range_low": or_low, "volume_ratio": ratio, "clv": float(row["clv"])},
                ))
                break

    return pd.DataFrame(rows)
