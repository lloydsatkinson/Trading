from __future__ import annotations

from datetime import date, time
from math import isfinite
from typing import Any, Callable

import numpy as np
import pandas as pd

from scanner.core.features import (
    attach_session_vwap,
    bucket_float,
    bucket_gap,
    bucket_rvol,
    bucket_time_of_day,
    close_location_value,
    prepare_intraday_bars,
)
from scanner.core.models import SignalRecord, market_cap_bucket, price_bucket
from scanner.core.replay import apply_entry_slippage
from .config import DanConfig
from .features import retained_gain_ratio

MinuteLoader = Callable[[str, date], pd.DataFrame]


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def dan_swing_setup_id(
    entry_family: str,
    base_length_sessions: int | None = None,
    breakout_reference: str | None = None,
) -> str:
    parts = [str(entry_family).upper()]
    if base_length_sessions is not None:
        parts.append(f"B{int(base_length_sessions)}")
    if breakout_reference:
        parts.append(str(breakout_reference).upper())
    return "_".join(parts)


def _daily_frame(daily_bars: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if daily_bars.empty:
        return pd.DataFrame()
    x = prepare_intraday_bars(daily_bars)
    x = x[x["symbol"].astype(str).eq(str(symbol))].copy()
    if x.empty:
        return x
    return x.sort_values("timestamp_et").drop_duplicates("session_date", keep="last").reset_index(drop=True)


def _minutes(loader: MinuteLoader, symbol: str, day: date) -> pd.DataFrame:
    raw = loader(symbol, day)
    if raw is None or raw.empty:
        return pd.DataFrame()
    x = prepare_intraday_bars(raw)
    return x[x["symbol"].astype(str).eq(str(symbol))].sort_values("timestamp_et").reset_index(drop=True)


def _regular_minutes(loader: MinuteLoader, symbol: str, day: date) -> pd.DataFrame:
    x = _minutes(loader, symbol, day)
    if x.empty:
        return x
    clock = x["timestamp_et"].dt.time
    return x[(clock >= time(9, 30)) & (clock < time(16, 0))].reset_index(drop=True)


def _next_bar_breakout(
    minutes: pd.DataFrame,
    breakout_level: float,
    start_idx: int = 0,
) -> tuple[pd.Series, pd.Series] | None:
    if minutes.empty or not np.isfinite(breakout_level):
        return None
    for idx in range(max(0, int(start_idx)), len(minutes) - 1):
        row = minutes.iloc[idx]
        entry = minutes.iloc[idx + 1]
        if row["session_date"] != entry["session_date"]:
            continue
        if float(row["close"]) > float(breakout_level):
            return row, entry
    return None


def _split_for_signal(
    context: dict[str, Any],
    signal_row: pd.Series,
    session_splits: dict[str, str] | None,
) -> str:
    fallback = str(context.get("split") or "forward")
    if not session_splits:
        return fallback
    signal_day = signal_row.get("session_date")
    if signal_day is None or pd.isna(signal_day):
        signal_day = pd.Timestamp(signal_row["timestamp_et"]).date()
    key = str(pd.Timestamp(signal_day).date())
    return str(session_splits.get(key, fallback))


def _emit(
    context: dict[str, Any],
    variant_id: str,
    setup_id: str,
    signal_row: pd.Series,
    entry_row: pd.Series,
    stop_reference: float,
    day0_hod: float,
    day0_retained_gain: float,
    entry_family: str,
    base_low: float,
    base_high: float,
    base_length_sessions: int | None,
    cfg: DanConfig,
    session_splits: dict[str, str] | None = None,
) -> dict[str, Any]:
    cap = _number(context.get("market_cap"))
    float_shares = _number(context.get("float_shares"))
    raw_entry = float(entry_row["open"])
    record = SignalRecord(
        strategy_id="DAN_IRISH",
        variant_id=variant_id,
        symbol=str(context.get("symbol") or signal_row.get("symbol") or "UNKNOWN"),
        date=str(context.get("date") or signal_row.get("session_date")),
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
        setup_metadata={
            "setup_id": setup_id,
            "day0_hod": day0_hod,
            "day0_retained_gain": day0_retained_gain,
            "entry_family": entry_family,
            "base_low": base_low,
            "base_high": base_high,
            "base_length_sessions": base_length_sessions,
        },
    ).to_dict()
    record.update({
        "split": _split_for_signal(context, signal_row, session_splits),
        "setup_id": setup_id,
        "price_bucket": price_bucket(raw_entry),
        "day0_hod": day0_hod,
        "day0_retained_gain": day0_retained_gain,
        "entry_family": entry_family,
        "base_low": base_low,
        "base_high": base_high,
        "base_length_sessions": base_length_sessions,
        "attribution": "DAN_INSPIRED",
        "_replay_mode": "swing",
        "pm_gap_pct": context.get("pm_gap_pct"),
        "pm_dollar_turnover": context.get("pm_dollar_turnover"),
        "opening_rvol": context.get("opening_rvol"),
    })
    return record


def generate_dan_swing_signals(
    day0_context: dict[str, Any],
    daily_bars: pd.DataFrame,
    minute_loader: MinuteLoader,
    cfg: DanConfig | None = None,
    session_splits: dict[str, str] | None = None,
) -> pd.DataFrame:
    cfg = cfg or DanConfig()
    symbol = str(day0_context.get("symbol") or "")
    prior_close = _number(day0_context.get("prior_close"))
    if not symbol or prior_close is None or prior_close <= 0 or daily_bars.empty:
        return pd.DataFrame()

    daily = _daily_frame(daily_bars, symbol)
    if daily.empty:
        return pd.DataFrame()
    day0_date = pd.Timestamp(day0_context.get("date")).date()
    day0_matches = daily.index[daily["session_date"].eq(day0_date)].tolist()
    if not day0_matches:
        return pd.DataFrame()
    day0_idx = int(day0_matches[0])
    day0 = daily.iloc[day0_idx]
    day0_hod = float(day0["high"])
    day0_low = float(day0["low"])
    day0_close = float(day0["close"])
    impulse_pct = day0_hod / prior_close - 1.0
    day0_retained = retained_gain_ratio(prior_close, day0_hod, day0_close)
    if (
        not np.isfinite(day0_retained)
        or impulse_pct < cfg.min_reference_extension_pct
        or day0_retained < cfg.min_retained_gain
    ):
        return pd.DataFrame()

    rows: list[dict[str, Any]] = []
    day0_minutes = _minutes(minute_loader, symbol, day0_date)

    # Late-day strength: only completed Day-0 regular-session bars qualify it.
    if not day0_minutes.empty:
        regular_with_vwap = attach_session_vwap(day0_minutes)
        clock = regular_with_vwap["timestamp_et"].dt.time
        late = regular_with_vwap[(clock >= time(15, 30)) & (clock < time(16, 0))].reset_index(drop=True)
        if not late.empty:
            late["clv"] = late.apply(close_location_value, axis=1)
            for idx in range(len(late) - 1):
                signal = late.iloc[idx]
                entry = late.iloc[idx + 1]
                session_vwap = _number(signal.get("session_vwap"))
                if (
                    session_vwap is not None
                    and float(signal["close"]) > session_vwap
                    and float(signal["clv"]) >= 0.70
                ):
                    setup = dan_swing_setup_id("OVERNIGHT_CLOSE")
                    rows.append(_emit(
                        day0_context, "DAN_OVERNIGHT_CLOSE_ENTRY", setup,
                        signal, entry, day0_low, day0_hod, day0_retained,
                        "OVERNIGHT_CLOSE", day0_low, day0_hod, None, cfg,
                        session_splits=session_splits,
                    ))
                    break

        # After-hours strength uses only completed AH bars and the completed Day-0 HOD.
        clock = day0_minutes["timestamp_et"].dt.time
        ah = day0_minutes[(clock >= time(16, 0)) & (clock < time(20, 0))].reset_index(drop=True)
        breakout = _next_bar_breakout(ah, day0_hod, start_idx=0)
        if breakout is not None:
            signal, entry = breakout
            setup = dan_swing_setup_id("OVERNIGHT_AH", breakout_reference="DAY0_HOD")
            rows.append(_emit(
                day0_context, "DAN_OVERNIGHT_AH_ENTRY", setup,
                signal, entry, day0_low, day0_hod, day0_retained,
                "OVERNIGHT_AH", day0_low, day0_hod, None, cfg,
                session_splits=session_splits,
            ))

    followup = daily.iloc[day0_idx + 1:].reset_index(drop=True)
    if followup.empty:
        return pd.DataFrame(rows)

    # Next-open is qualified entirely from Day 0. Only the entry price/timestamp comes from Day 1.
    next_day = followup.iloc[0]["session_date"]
    next_minutes = _regular_minutes(minute_loader, symbol, next_day)
    if not next_minutes.empty:
        entry = next_minutes.iloc[0]
        setup = dan_swing_setup_id("OVERNIGHT_NEXT_OPEN")
        rows.append(_emit(
            day0_context, "DAN_OVERNIGHT_NEXT_OPEN", setup,
            day0, entry, day0_low, day0_hod, day0_retained,
            "OVERNIGHT_NEXT_OPEN", day0_low, day0_hod, None, cfg,
            session_splits=session_splits,
        ))

        # Day-2 continuation base is frozen after the configured number of opening bars.
        base_n = int(cfg.min_consolidation_minutes)
        if base_n > 0 and len(next_minutes) >= base_n + 2:
            base = next_minutes.iloc[:base_n]
            base_high = float(pd.to_numeric(base["high"], errors="coerce").max())
            base_low = float(pd.to_numeric(base["low"], errors="coerce").min())
            breakout = _next_bar_breakout(next_minutes, base_high, start_idx=base_n)
            if breakout is not None:
                signal, entry = breakout
                setup = dan_swing_setup_id("DAY2", base_length_sessions=1, breakout_reference="BASE_HIGH")
                rows.append(_emit(
                    day0_context, "DAN_DAY2_CONTINUATION", setup,
                    signal, entry, base_low, day0_hod, day0_retained,
                    "DAY2", base_low, base_high, 1, cfg,
                    session_splits=session_splits,
                ))

    # Multi-day compression bases contain completed daily sessions only. The breakout session is never in its own base.
    max_base = min(5, len(followup) - 1)
    for base_length in range(1, max_base + 1):
        base_daily = followup.iloc[:base_length]
        breakout_day = followup.iloc[base_length]["session_date"]
        base_high = float(pd.to_numeric(base_daily["high"], errors="coerce").max())
        base_low = float(pd.to_numeric(base_daily["low"], errors="coerce").min())
        breakout_minutes = _regular_minutes(minute_loader, symbol, breakout_day)
        breakout = _next_bar_breakout(breakout_minutes, base_high, start_idx=0)
        if breakout is None:
            continue
        signal, entry = breakout
        setup = dan_swing_setup_id(
            "MULTIDAY", base_length_sessions=base_length, breakout_reference="BASE_HIGH"
        )
        rows.append(_emit(
            day0_context, "DAN_MULTIDAY_COMPRESSION", setup,
            signal, entry, base_low, day0_hod, day0_retained,
            "MULTIDAY", base_low, base_high, base_length, cfg,
            session_splits=session_splits,
        ))

    return pd.DataFrame(rows)
