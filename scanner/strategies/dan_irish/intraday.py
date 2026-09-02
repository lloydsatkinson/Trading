from __future__ import annotations

from dataclasses import replace
from math import isfinite
from typing import Any, Iterable

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
from scanner.core.models import SignalRecord, market_cap_bucket, price_bucket
from scanner.core.replay import apply_entry_slippage
from .config import (
    BREAKOUT_VOLUME_RATIO_GRID,
    CONSOLIDATION_MINUTES_GRID,
    DanConfig,
)
from .features import retained_gain_checkpoint_values, retained_gain_ratio


DEFAULT_BREAKOUT_REFERENCES = ("BASE_HIGH", "HOD", "PM_HIGH")


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def dan_intraday_setup_id(consolidation_minutes: int, breakout_reference: str, min_volume_ratio: float) -> str:
    ref = str(breakout_reference).upper()
    ratio = str(float(min_volume_ratio)).replace(".", "P")
    return f"C{int(consolidation_minutes)}_{ref}_V{ratio}"


def _regular_session(bars: pd.DataFrame) -> pd.DataFrame:
    if bars.empty:
        return bars.copy()
    x = attach_session_vwap(bars)
    clock = x["timestamp_et"].dt.time
    return x[(clock >= pd.Timestamp("09:30").time()) & (clock < pd.Timestamp("16:00").time())].reset_index(drop=True)


def _prepare_intraday_features(bars: pd.DataFrame, cfg: DanConfig) -> pd.DataFrame:
    x = _regular_session(bars)
    if x.empty:
        return x
    x = x.copy()
    x["prior_volume_median"] = rolling_prior_volume_median(x, cfg.volume_lookback_bars)
    x["volume_ratio"] = pd.to_numeric(x["volume"], errors="coerce") / x["prior_volume_median"].replace(0, np.nan)
    x["clv"] = x.apply(close_location_value, axis=1)
    return x


def _breakout_level(
    x: pd.DataFrame,
    idx: int,
    base_high: float,
    context: dict[str, Any],
    breakout_reference: str,
) -> float | None:
    reference = str(breakout_reference).upper()
    if reference == "BASE_HIGH":
        return float(base_high)
    if reference == "PM_HIGH":
        return _number(context.get("pm_high"))
    if reference == "HOD":
        # Completed bars only: the current confirmation bar cannot set the level it breaks.
        prior = pd.to_numeric(x.iloc[:idx]["high"], errors="coerce").dropna()
        return float(prior.max()) if not prior.empty else None
    raise ValueError(f"Unsupported Dan breakout reference: {breakout_reference}")


def generate_dan_intraday_signals(
    bars: pd.DataFrame,
    context: dict[str, Any],
    cfg: DanConfig | None = None,
    breakout_reference: str = "BASE_HIGH",
    *,
    _prepared_frame: pd.DataFrame | None = None,
) -> pd.DataFrame:
    cfg = cfg or DanConfig()
    reference_type = str(breakout_reference).upper()
    if reference_type not in DEFAULT_BREAKOUT_REFERENCES:
        raise ValueError(f"Unsupported Dan breakout reference: {breakout_reference}")
    if bars.empty or context.get("dan_candidate") is False:
        return pd.DataFrame()
    prior_close = _number(context.get("prior_close"))
    if prior_close is None or prior_close <= 0:
        return pd.DataFrame()

    x = _prepared_frame.copy() if _prepared_frame is not None else _prepare_intraday_features(bars, cfg)
    if x.empty:
        return pd.DataFrame()

    minimum_base = int(cfg.min_consolidation_minutes)
    first_confirmation = minimum_base + 1
    for idx in range(first_confirmation, len(x)):
        next_idx = idx + 1
        if next_idx >= len(x):
            continue
        if x.loc[next_idx, "session_date"] != x.loc[idx, "session_date"]:
            continue

        # The impulse peak must be fully known before the minimum base begins.
        # For a confirmation at idx, only bars through idx-minimum_base-1 can be
        # the impulse anchor. This allows a continuing initial spike to replace
        # an earlier threshold-crossing bar without looking at future bars.
        impulse_window = x.iloc[: idx - minimum_base]
        if impulse_window.empty:
            continue
        impulse_highs = pd.to_numeric(impulse_window["high"], errors="coerce").dropna()
        if impulse_highs.empty:
            continue
        impulse_idx = int(impulse_highs.idxmax())
        impulse_high = float(x.loc[impulse_idx, "high"])
        impulse_pct = impulse_high / prior_close - 1.0
        if impulse_high <= prior_close or impulse_pct < cfg.min_reference_extension_pct:
            continue

        base = x.iloc[impulse_idx + 1:idx]
        if len(base) < minimum_base:
            continue
        base_low = float(pd.to_numeric(base["low"], errors="coerce").min())
        base_high = float(pd.to_numeric(base["high"], errors="coerce").max())
        retained = retained_gain_ratio(prior_close, impulse_high, base_low)
        if not np.isfinite(retained):
            continue
        pullback_depth = (impulse_high - base_low) / (impulse_high - prior_close)
        if retained < cfg.min_retained_gain or pullback_depth > cfg.max_pullback_depth:
            continue

        row = x.loc[idx]
        volume_ratio = _number(row.get("volume_ratio"))
        if volume_ratio is None or volume_ratio < cfg.min_breakout_volume_ratio:
            continue
        level = _breakout_level(x, idx, base_high, context, reference_type)
        if level is None or not np.isfinite(level) or float(row["close"]) <= float(level):
            continue

        checkpoints = retained_gain_checkpoint_values(
            x,
            impulse_timestamp=x.loc[impulse_idx, "timestamp_et"],
            impulse_start_price=prior_close,
            impulse_high_price=impulse_high,
        )
        entry = x.loc[next_idx]
        raw_entry = float(entry["open"])
        cap = _number(context.get("market_cap"))
        float_shares = _number(context.get("float_shares"))
        setup_id = dan_intraday_setup_id(
            minimum_base, reference_type, cfg.min_breakout_volume_ratio
        )
        setup_metadata = {
            "setup_id": setup_id,
            "impulse_pct": impulse_pct,
            "impulse_high": impulse_high,
            "base_low": base_low,
            "base_high": base_high,
            "retained_gain_ratio": retained,
            "pullback_depth": pullback_depth,
            "breakout_volume_ratio": volume_ratio,
            "breakout_reference_type": reference_type,
            "breakout_level": float(level),
            "clv": float(row["clv"]),
            "session_vwap": _number(row.get("session_vwap")),
            **checkpoints,
        }
        record = SignalRecord(
            strategy_id="DAN_IRISH",
            variant_id="DAN_INTRADAY_SECONDARY",
            symbol=str(context.get("symbol") or row.get("symbol") or "UNKNOWN"),
            date=str(context.get("date") or row["session_date"]),
            direction="LONG",
            signal_timestamp=row["timestamp_et"],
            reference_price=float(row["close"]),
            entry_timestamp=entry["timestamp_et"],
            entry_price_raw=raw_entry,
            entry_price_slipped=apply_entry_slippage(raw_entry, "LONG", cfg.slippage_bps),
            stop_reference=base_low,
            market_cap=cap,
            market_cap_bucket=market_cap_bucket(cap),
            float_shares=float_shares,
            float_bucket=bucket_float(float_shares),
            gap_bucket=bucket_gap(context.get("pm_gap_pct")),
            rvol_bucket=bucket_rvol(context.get("opening_rvol")),
            time_of_day_bucket=bucket_time_of_day(row["timestamp_et"]),
            catalyst_class=str(context.get("catalyst_class") or "UNKNOWN"),
            setup_metadata=setup_metadata,
        ).to_dict()
        record.update({
            "split": str(context.get("split") or "forward"),
            "setup_id": setup_id,
            "price_bucket": price_bucket(raw_entry),
            "impulse_pct": impulse_pct,
            "impulse_high": impulse_high,
            "base_low": base_low,
            "base_high": base_high,
            "retained_gain_ratio": retained,
            "pullback_depth": pullback_depth,
            "consolidation_minutes": int(len(base)),
            "breakout_volume_ratio": volume_ratio,
            "breakout_reference_type": reference_type,
            "breakout_level": float(level),
            "attribution": "DAN_DERIVED",
            "_replay_mode": "intraday",
            "pm_gap_pct": context.get("pm_gap_pct"),
            "pm_dollar_turnover": context.get("pm_dollar_turnover"),
            "opening_rvol": context.get("opening_rvol"),
            **checkpoints,
        })
        return pd.DataFrame([record])
    return pd.DataFrame()


def generate_dan_intraday_signal_grid(
    bars: pd.DataFrame,
    context: dict[str, Any],
    cfg: DanConfig | None = None,
    consolidation_minutes: Iterable[int] = CONSOLIDATION_MINUTES_GRID,
    breakout_references: Iterable[str] = DEFAULT_BREAKOUT_REFERENCES,
    volume_ratios: Iterable[float] = BREAKOUT_VOLUME_RATIO_GRID,
) -> pd.DataFrame:
    """Generate distinct entry-timing hypotheses without pooling setup identities."""
    cfg = cfg or DanConfig()
    prepared = _prepare_intraday_features(bars, cfg)
    if prepared.empty:
        return pd.DataFrame()
    frames: list[pd.DataFrame] = []
    for minutes in consolidation_minutes:
        for reference in breakout_references:
            for ratio in volume_ratios:
                combo = replace(
                    cfg,
                    min_consolidation_minutes=int(minutes),
                    min_breakout_volume_ratio=float(ratio),
                )
                signal = generate_dan_intraday_signals(
                    bars,
                    context,
                    combo,
                    breakout_reference=str(reference),
                    _prepared_frame=prepared,
                )
                if not signal.empty:
                    frames.append(signal)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True, sort=False).drop_duplicates(
        subset=["symbol", "entry_timestamp", "setup_id"], keep="first"
    ).reset_index(drop=True)
