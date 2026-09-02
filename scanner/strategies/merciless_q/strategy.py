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

Event = tuple[int, str, float, dict[str, Any]]


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
    high, low = float(row["high"]), float(row["low"])
    width = high - low
    if not np.isfinite(width) or width <= 0:
        return 0.0
    return float(np.clip((high - max(float(row["open"]), float(row["close"]))) / width, 0.0, 1.0))


def _score(context: dict[str, Any], cfg: MercilessConfig, setup: dict[str, Any]) -> float:
    score = 0.0
    gap = _number(context.get("pm_gap_pct")) or 0.0
    turnover = _number(context.get("pm_dollar_turnover")) or 0.0
    rvol = _number(context.get("opening_rvol"))
    impulse = float(setup.get("impulse_pct", 0.0))
    velocity = float(setup.get("impulse_velocity_pct_per_min", 0.0))
    retained = float(setup.get("retained_gain", 0.0))
    pullback = float(setup.get("pullback_fraction", 1.0))
    volume_ratio = float(setup.get("volume_ratio", 0.0))
    clv = float(setup.get("clv", 0.5))
    wick = float(setup.get("upper_wick_ratio", 1.0))
    score += 8.0 if gap >= cfg.min_gap_pct else 0.0
    score += 8.0 if turnover >= 2.0 * cfg.min_pm_dollar_turnover else 0.0
    score += 9.0 if rvol is not None and rvol >= 5.0 else 0.0
    score += 10.0 if impulse >= cfg.min_impulse_pct else 0.0
    score += 10.0 if velocity >= cfg.min_impulse_velocity_pct_per_min else 0.0
    score += 10.0 if retained >= cfg.min_retained_gain else 0.0
    score += 10.0 if pullback <= min(cfg.max_pullback_fraction, 0.30) else 0.0
    score += 8.0 if volume_ratio >= cfg.min_breakout_volume_ratio else 0.0
    score += 7.0 if clv >= 0.75 else 0.0
    score += 8.0 if wick <= 0.25 else 0.0
    score += 7.0 if clv >= cfg.min_clv else 0.0
    catalyst = str(context.get("catalyst_class") or "UNKNOWN").upper()
    score += 5.0 if catalyst not in {"", "UNKNOWN", "NONE", "NAN"} else 0.0
    return float(np.clip(score, 0.0, 100.0))


def _impulse_metrics(x: pd.DataFrame, prior_close: float, impulse_idx: int, through_idx: int) -> tuple[float, float, float]:
    history = x.loc[impulse_idx:through_idx]
    peak_idx = pd.to_numeric(history["high"], errors="coerce").idxmax()
    peak = float(history.loc[peak_idx, "high"])
    elapsed = max(1.0, float((pd.Timestamp(history.loc[peak_idx, "timestamp_et"]) - pd.Timestamp(x.loc[0, "timestamp_et"])).total_seconds() / 60.0))
    impulse = peak / prior_close - 1.0
    return peak, impulse, impulse / elapsed


def _base_setup(x: pd.DataFrame, prior_close: float, impulse_idx: int, trigger_idx: int, low: float) -> dict[str, Any]:
    peak, impulse, velocity = _impulse_metrics(x, prior_close, impulse_idx, max(impulse_idx, trigger_idx - 1))
    denom = max(peak - prior_close, 1e-12)
    row = x.loc[trigger_idx]
    return {
        "first_impulse_timestamp": x.loc[impulse_idx, "timestamp_et"],
        "peak_price": peak,
        "impulse_pct": impulse,
        "impulse_velocity_pct_per_min": velocity,
        "pullback_low": low,
        "retained_gain": (low - prior_close) / denom,
        "pullback_fraction": (peak - low) / denom,
        "volume_ratio": float(row["volume_ratio"]) if pd.notna(row["volume_ratio"]) else 0.0,
        "clv": float(row["clv"]),
        "upper_wick_ratio": float(row["upper_wick_ratio"]),
    }


def _signal(context: dict[str, Any], variant_id: str, x: pd.DataFrame, signal_idx: int, stop_reference: float, cfg: MercilessConfig, setup: dict[str, Any], impulse_idx: int, sequence_number: int, prior_signal_idx: int | None) -> dict[str, Any]:
    signal_row, entry_row = x.loc[signal_idx], x.loc[signal_idx + 1]
    cap = _number(context.get("market_cap"))
    float_shares = _number(context.get("float_shares"))
    raw_entry = float(entry_row["open"])
    record = SignalRecord(
        strategy_id="MERCILESS_Q",
        variant_id=variant_id,
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
    minutes_since = np.nan
    if prior_signal_idx is not None:
        minutes_since = float((pd.Timestamp(signal_row["timestamp_et"]) - pd.Timestamp(x.loc[prior_signal_idx, "timestamp_et"])).total_seconds() / 60.0)
    record.update({
        "split": str(context.get("split") or "forward"),
        "pm_gap_pct": context.get("pm_gap_pct"),
        "pm_dollar_turnover": context.get("pm_dollar_turnover"),
        "opening_rvol": context.get("opening_rvol"),
        "mmq_score": _score(context, cfg, setup),
        "sequence_number": int(sequence_number),
        "minutes_since_prior_signal": minutes_since,
        "runner_age_minutes": float((pd.Timestamp(signal_row["timestamp_et"]) - pd.Timestamp(x.loc[impulse_idx, "timestamp_et"])).total_seconds() / 60.0),
    })
    return record


def _first_pullback_events(x: pd.DataFrame, prior_close: float, impulse_idx: int, cfg: MercilessConfig) -> list[Event]:
    events: list[Event] = []
    start = impulse_idx + cfg.min_contraction_bars + 1
    for trigger_idx in range(start, len(x) - 1):
        contraction_start = max(impulse_idx + 1, trigger_idx - cfg.max_contraction_bars)
        contraction = x.loc[contraction_start: trigger_idx - 1]
        if len(contraction) < cfg.min_contraction_bars:
            continue
        low = float(contraction["low"].min())
        setup = _base_setup(x, prior_close, impulse_idx, trigger_idx, low)
        if setup["retained_gain"] < cfg.min_retained_gain or setup["pullback_fraction"] > cfg.max_pullback_fraction:
            continue
        resistance = float(contraction["high"].max())
        row = x.loc[trigger_idx]
        if (float(row["close"]) > resistance and setup["volume_ratio"] >= cfg.min_breakout_volume_ratio
                and setup["clv"] >= cfg.min_clv and setup["upper_wick_ratio"] <= cfg.max_upper_wick_ratio):
            setup.update({
                "contraction_bars": int(len(contraction)),
                "contraction_high": resistance,
                "reset_anchor_idx": max(impulse_idx + 1, trigger_idx - cfg.min_contraction_bars),
            })
            events.append((trigger_idx, "MMQ_FIRST_PULLBACK", low, setup))
    return events


def _micro_breakout_events(x: pd.DataFrame, prior_close: float, impulse_idx: int, cfg: MercilessConfig) -> list[Event]:
    events: list[Event] = []
    for trigger_idx in range(impulse_idx + 3, len(x) - 1):
        window_start = max(impulse_idx, trigger_idx - 4)
        window = x.loc[window_start: trigger_idx - 1]
        if len(window) < 3:
            continue
        resistance = float(window["high"].max())
        tests = int((pd.to_numeric(window["high"], errors="coerce") >= resistance * 0.995).sum())
        if tests < 2:
            continue
        low = float(window["low"].min())
        setup = _base_setup(x, prior_close, impulse_idx, trigger_idx, low)
        row = x.loc[trigger_idx]
        if (float(row["close"]) > resistance and setup["volume_ratio"] >= cfg.min_breakout_volume_ratio
                and setup["clv"] >= cfg.min_clv and setup["upper_wick_ratio"] <= cfg.max_upper_wick_ratio):
            setup.update({
                "resistance": resistance,
                "resistance_tests": tests,
                "compression_bars": int(len(window)),
                "reset_anchor_idx": max(impulse_idx + 1, trigger_idx - 3),
            })
            events.append((trigger_idx, "MMQ_MICRO_BREAKOUT", low, setup))
    return events


def _vwap_reset_events(x: pd.DataFrame, prior_close: float, impulse_idx: int, cfg: MercilessConfig) -> list[Event]:
    events: list[Event] = []
    for touch_idx in range(impulse_idx + 1, len(x) - 2):
        vwap_touch = _number(x.loc[touch_idx, "session_vwap"])
        if vwap_touch is None or not (float(x.loc[touch_idx, "low"]) <= vwap_touch and float(x.loc[touch_idx, "close"]) <= vwap_touch):
            continue
        reset_low = float(x.loc[max(impulse_idx + 1, touch_idx - 3):touch_idx, "low"].min())
        for trigger_idx in range(touch_idx + 1, min(len(x) - 1, touch_idx + 4)):
            row = x.loc[trigger_idx]
            vwap = _number(row["session_vwap"])
            if vwap is None:
                continue
            setup = _base_setup(x, prior_close, impulse_idx, trigger_idx, reset_low)
            if setup["retained_gain"] < cfg.min_retained_gain:
                continue
            if (float(row["close"]) > vwap and setup["volume_ratio"] >= cfg.min_breakout_volume_ratio
                    and setup["clv"] >= cfg.min_clv and setup["upper_wick_ratio"] <= cfg.max_upper_wick_ratio):
                setup.update({
                    "vwap_touch_timestamp": x.loc[touch_idx, "timestamp_et"],
                    "reclaim_vwap": vwap,
                    "reset_anchor_idx": touch_idx,
                })
                events.append((trigger_idx, "MMQ_VWAP_RESET", reset_low, setup))
                break
    return events


def _trap_reclaim_events(x: pd.DataFrame, prior_close: float, impulse_idx: int, cfg: MercilessConfig) -> list[Event]:
    events: list[Event] = []
    for break_idx in range(impulse_idx + 3, len(x) - 2):
        prior = x.loc[max(impulse_idx + 1, break_idx - 3): break_idx - 1]
        if len(prior) < 2:
            continue
        broken_level = float(prior["low"].min())
        break_row = x.loc[break_idx]
        if not (float(break_row["low"]) < broken_level and float(break_row["close"]) < broken_level):
            continue
        trap_low = float(break_row["low"])
        trigger_idx = break_idx + 1
        row = x.loc[trigger_idx]
        setup = _base_setup(x, prior_close, impulse_idx, trigger_idx, trap_low)
        if (float(row["close"]) > broken_level and setup["volume_ratio"] >= cfg.min_breakout_volume_ratio
                and setup["clv"] >= cfg.min_clv and setup["upper_wick_ratio"] <= cfg.max_upper_wick_ratio):
            setup.update({
                "broken_level": broken_level,
                "trap_break_timestamp": break_row["timestamp_et"],
                "reset_anchor_idx": break_idx,
            })
            events.append((trigger_idx, "MMQ_TRAP_RECLAIM", trap_low, setup))
    return events


def _accept_events(events: list[Event], cfg: MercilessConfig) -> list[Event]:
    accepted: list[Event] = []
    last_idx: int | None = None
    last_variant_idx: dict[str, int] = {}
    used_signal_indices: set[int] = set()
    priority = {"MMQ_FIRST_PULLBACK": 0, "MMQ_MICRO_BREAKOUT": 1, "MMQ_VWAP_RESET": 2, "MMQ_TRAP_RECLAIM": 3}
    for event in sorted(events, key=lambda e: (e[0], priority.get(e[1], 99))):
        idx, variant, _, setup = event
        if idx in used_signal_indices:
            continue
        if last_idx is not None and idx - last_idx < cfg.cooldown_bars:
            continue
        previous_variant_idx = last_variant_idx.get(variant)
        reset_anchor = int(setup.get("reset_anchor_idx", idx))
        if previous_variant_idx is not None and reset_anchor <= previous_variant_idx:
            continue
        accepted.append(event)
        used_signal_indices.add(idx)
        last_idx = idx
        last_variant_idx[variant] = idx
        if len(accepted) >= cfg.max_signals_per_symbol:
            break
    return accepted


def generate_merciless_signals(bars: pd.DataFrame, context: dict[str, Any], cfg: MercilessConfig | None = None) -> pd.DataFrame:
    cfg = cfg or MercilessConfig()
    if bars.empty or not _candidate_ok(context, cfg):
        return pd.DataFrame()
    prior_close = float(context["prior_close"])
    x = attach_session_vwap(bars)
    if x.empty:
        return pd.DataFrame()
    x["prior_volume_median"] = rolling_prior_volume_median(x, cfg.volume_lookback_bars)
    x["volume_ratio"] = pd.to_numeric(x["volume"], errors="coerce") / x["prior_volume_median"].replace(0, np.nan)
    x["clv"] = x.apply(close_location_value, axis=1)
    x["upper_wick_ratio"] = x.apply(_upper_wick_ratio, axis=1)
    x["running_high"] = pd.to_numeric(x["high"], errors="coerce").cummax()
    x["impulse_pct"] = x["running_high"] / prior_close - 1.0
    candidates = x.index[x["impulse_pct"] >= cfg.min_impulse_pct].tolist()
    if not candidates:
        return pd.DataFrame()
    impulse_idx = int(candidates[0])
    elapsed = max(1.0, float((pd.Timestamp(x.loc[impulse_idx, "timestamp_et"]) - pd.Timestamp(x.loc[0, "timestamp_et"])).total_seconds() / 60.0))
    if float(x.loc[impulse_idx, "impulse_pct"]) / elapsed < cfg.min_impulse_velocity_pct_per_min:
        return pd.DataFrame()

    events: list[Event] = []
    events.extend(_first_pullback_events(x, prior_close, impulse_idx, cfg))
    events.extend(_micro_breakout_events(x, prior_close, impulse_idx, cfg))
    events.extend(_vwap_reset_events(x, prior_close, impulse_idx, cfg))
    events.extend(_trap_reclaim_events(x, prior_close, impulse_idx, cfg))
    accepted = _accept_events(events, cfg)
    rows: list[dict[str, Any]] = []
    prior_idx: int | None = None
    for sequence_number, (idx, variant, stop, setup) in enumerate(accepted, start=1):
        if idx + 1 >= len(x) or x.loc[idx + 1, "session_date"] != x.loc[idx, "session_date"]:
            continue
        rows.append(_signal(context, variant, x, idx, stop, cfg, setup, impulse_idx, sequence_number, prior_idx))
        prior_idx = idx
    return pd.DataFrame(rows)
