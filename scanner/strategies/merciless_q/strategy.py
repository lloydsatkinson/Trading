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
from scanner.core.models import SignalRecord, market_cap_bucket, market_cap_in_primary_universe
from scanner.core.replay import apply_entry_slippage
from .config import MercilessConfig


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def _candidate_ok(context: dict[str, Any], cfg: MercilessConfig) -> bool:
    prior_close = _number(context.get("prior_close"))
    if prior_close is None or not (cfg.min_price <= prior_close <= cfg.max_price):
        return False
    cap = _number(context.get("market_cap"))
    if cap is not None and not market_cap_in_primary_universe(cap):
        return False
    gap = _number(context.get("pm_gap_pct"))
    turnover = _number(context.get("pm_dollar_turnover"))
    rvol = _number(context.get("opening_rvol"))
    if gap is None or gap < cfg.min_gap_pct:
        return False
    if turnover is None or turnover < cfg.min_pm_dollar_turnover:
        return False
    if rvol is not None and rvol < cfg.min_opening_rvol:
        return False
    return True


def _upper_wick_ratio(row: pd.Series) -> float:
    high = float(row["high"])
    low = float(row["low"])
    close = float(row["close"])
    open_ = float(row["open"])
    width = high - low
    if not np.isfinite(width) or width <= 0:
        return 0.0
    return float(np.clip((high - max(open_, close)) / width, 0.0, 1.0))


def _score(
    context: dict[str, Any],
    cfg: MercilessConfig,
    impulse_pct: float,
    impulse_velocity: float,
    retained_gain: float,
    pullback_fraction: float,
    volume_ratio: float,
    clv: float,
    upper_wick_ratio: float,
) -> float:
    score = 0.0
    gap = _number(context.get("pm_gap_pct")) or 0.0
    turnover = _number(context.get("pm_dollar_turnover")) or 0.0
    rvol = _number(context.get("opening_rvol"))

    if gap >= cfg.min_gap_pct:
        score += 8.0
    if turnover >= 2.0 * cfg.min_pm_dollar_turnover:
        score += 8.0
    if rvol is not None and rvol >= 5.0:
        score += 9.0

    if impulse_pct >= cfg.min_impulse_pct:
        score += 10.0
    if impulse_velocity >= cfg.min_impulse_velocity_pct_per_min:
        score += 10.0

    if retained_gain >= cfg.min_retained_gain:
        score += 10.0
    if pullback_fraction <= min(cfg.max_pullback_fraction, 0.30):
        score += 10.0

    if volume_ratio >= cfg.min_breakout_volume_ratio:
        score += 8.0
    if clv >= 0.75:
        score += 7.0

    if upper_wick_ratio <= 0.25:
        score += 8.0
    if clv >= cfg.min_clv:
        score += 7.0

    catalyst = str(context.get("catalyst_class") or "UNKNOWN").upper()
    if catalyst not in {"", "UNKNOWN", "NONE", "NAN"}:
        score += 5.0
    return float(np.clip(score, 0.0, 100.0))


def _signal(
    context: dict[str, Any],
    signal_row: pd.Series,
    entry_row: pd.Series,
    stop_reference: float,
    cfg: MercilessConfig,
    setup: dict[str, Any],
    first_impulse_timestamp: Any,
) -> dict[str, Any]:
    cap = _number(context.get("market_cap"))
    float_shares = _number(context.get("float_shares"))
    raw_entry = float(entry_row["open"])
    score = _score(
        context,
        cfg,
        float(setup["impulse_pct"]),
        float(setup["impulse_velocity_pct_per_min"]),
        float(setup["retained_gain"]),
        float(setup["pullback_fraction"]),
        float(setup["volume_ratio"]),
        float(setup["clv"]),
        float(setup["upper_wick_ratio"]),
    )
    record = SignalRecord(
        strategy_id="MERCILESS_Q",
        variant_id="MMQ_FIRST_PULLBACK",
        symbol=str(context.get("symbol") or signal_row.get("symbol") or "UNKNOWN"),
        date=str(context.get("date") or signal_row["session_date"]),
        direction="LONG",
        signal_timestamp=signal_row["timestamp_et"],
        reference_price=float(signal_row["close"]),
        entry_timestamp=entry_row["timestamp_et"],
        entry_price_raw=raw_entry,
        entry_price_slipped=apply_entry_slippage(raw_entry, "LONG", cfg.slippage_bps),
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
    signal_ts = pd.Timestamp(signal_row["timestamp_et"])
    impulse_ts = pd.Timestamp(first_impulse_timestamp)
    record["split"] = str(context.get("split") or "forward")
    record["pm_gap_pct"] = context.get("pm_gap_pct")
    record["pm_dollar_turnover"] = context.get("pm_dollar_turnover")
    record["opening_rvol"] = context.get("opening_rvol")
    record["mmq_score"] = score
    record["sequence_number"] = 1
    record["minutes_since_prior_signal"] = np.nan
    record["runner_age_minutes"] = float((signal_ts - impulse_ts).total_seconds() / 60.0)
    return record


def generate_merciless_signals(
    bars: pd.DataFrame,
    context: dict[str, Any],
    cfg: MercilessConfig | None = None,
) -> pd.DataFrame:
    cfg = cfg or MercilessConfig()
    if bars.empty or not _candidate_ok(context, cfg):
        return pd.DataFrame()

    prior_close = float(context["prior_close"])
    x = attach_session_vwap(bars)
    if x.empty:
        return pd.DataFrame()
    x["prior_volume_median"] = rolling_prior_volume_median(x, cfg.volume_lookback_bars)
    x["volume_ratio"] = (
        pd.to_numeric(x["volume"], errors="coerce")
        / x["prior_volume_median"].replace(0, np.nan)
    )
    x["clv"] = x.apply(close_location_value, axis=1)
    x["upper_wick_ratio"] = x.apply(_upper_wick_ratio, axis=1)
    x["running_high"] = pd.to_numeric(x["high"], errors="coerce").cummax()
    x["impulse_pct"] = x["running_high"] / prior_close - 1.0

    impulse_candidates = x.index[x["impulse_pct"] >= cfg.min_impulse_pct].tolist()
    if not impulse_candidates:
        return pd.DataFrame()
    impulse_idx = int(impulse_candidates[0])
    impulse_ts = x.loc[impulse_idx, "timestamp_et"]
    elapsed = max(
        1.0,
        float((pd.Timestamp(impulse_ts) - pd.Timestamp(x.loc[0, "timestamp_et"])).total_seconds() / 60.0),
    )
    initial_impulse_pct = float(x.loc[impulse_idx, "impulse_pct"])
    initial_velocity = initial_impulse_pct / elapsed
    if initial_velocity < cfg.min_impulse_velocity_pct_per_min:
        return pd.DataFrame()

    first_trigger_idx = impulse_idx + cfg.min_contraction_bars + 1
    if first_trigger_idx >= len(x) - 0:
        return pd.DataFrame()

    for trigger_idx in range(first_trigger_idx, len(x) - 1):
        contraction_start = max(impulse_idx + 1, trigger_idx - cfg.max_contraction_bars)
        contraction = x.loc[contraction_start: trigger_idx - 1]
        if len(contraction) < cfg.min_contraction_bars:
            continue

        history = x.loc[impulse_idx: trigger_idx - 1]
        peak_price = float(pd.to_numeric(history["high"], errors="coerce").max())
        pullback_low = float(pd.to_numeric(contraction["low"], errors="coerce").min())
        denominator = peak_price - prior_close
        if not np.isfinite(denominator) or denominator <= 0:
            continue
        retained_gain = (pullback_low - prior_close) / denominator
        pullback_fraction = (peak_price - pullback_low) / denominator
        if retained_gain < cfg.min_retained_gain or pullback_fraction > cfg.max_pullback_fraction:
            continue

        contraction_high = float(pd.to_numeric(contraction["high"], errors="coerce").max())
        row = x.loc[trigger_idx]
        entry = x.loc[trigger_idx + 1]
        if entry["session_date"] != row["session_date"]:
            continue
        volume_ratio = _number(row["volume_ratio"])
        if volume_ratio is None:
            continue
        clv = float(row["clv"])
        wick = float(row["upper_wick_ratio"])
        if not (
            float(row["close"]) > contraction_high
            and volume_ratio >= cfg.min_breakout_volume_ratio
            and clv >= cfg.min_clv
            and wick <= cfg.max_upper_wick_ratio
        ):
            continue

        peak_timestamp = history.loc[pd.to_numeric(history["high"], errors="coerce").idxmax(), "timestamp_et"]
        peak_elapsed = max(
            1.0,
            float((pd.Timestamp(peak_timestamp) - pd.Timestamp(x.loc[0, "timestamp_et"])).total_seconds() / 60.0),
        )
        impulse_pct = peak_price / prior_close - 1.0
        impulse_velocity = impulse_pct / peak_elapsed
        setup = {
            "first_impulse_timestamp": impulse_ts,
            "peak_price": peak_price,
            "impulse_pct": impulse_pct,
            "impulse_velocity_pct_per_min": impulse_velocity,
            "contraction_bars": int(len(contraction)),
            "contraction_high": contraction_high,
            "pullback_low": pullback_low,
            "retained_gain": retained_gain,
            "pullback_fraction": pullback_fraction,
            "volume_ratio": volume_ratio,
            "clv": clv,
            "upper_wick_ratio": wick,
        }
        return pd.DataFrame([
            _signal(
                context,
                row,
                entry,
                pullback_low,
                cfg,
                setup,
                impulse_ts,
            )
        ])

    return pd.DataFrame()
