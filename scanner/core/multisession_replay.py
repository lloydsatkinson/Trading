from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable

import numpy as np
import pandas as pd

from scanner.core.replay import raw_return_pct

ET = "America/New_York"


def _direction(value: str) -> str:
    direction = str(value).upper()
    if direction not in {"LONG", "SHORT"}:
        raise ValueError("direction must be LONG or SHORT")
    return direction


def _et_timestamp(value: Any) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize(ET) if ts.tzinfo is None else ts.tz_convert(ET)


def _as_date(value: Any) -> object:
    return pd.Timestamp(value).date()


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
    x["session_date"] = x["timestamp_et"].dt.date
    for column in ("open", "high", "low", "close", "volume", "vwap"):
        if column in x.columns:
            x[column] = pd.to_numeric(x[column], errors="coerce")
    return x.dropna(subset=["timestamp_et", "open", "high", "low", "close"]).sort_values("timestamp_et").reset_index(drop=True)


@dataclass(frozen=True)
class SwingReplayRule:
    stop_mode: str = "PCT"
    stop_pct: float | None = None
    stop_price: float | None = None
    atr_multiple: float | None = None
    target_pct: float | None = None
    target_price: float | None = None
    target_r_multiple: float | None = None
    trailing_exit: str | None = None
    max_hold_sessions: int = 1

    @property
    def rule_id(self) -> str:
        mode = str(self.stop_mode or "PCT").upper()
        if self.stop_price is not None:
            stop = "SSTRUCT" if mode != "PCT" else f"SP{float(self.stop_price):.4f}"
        elif self.stop_pct is not None:
            stop = f"S{int(round(float(self.stop_pct) * 100)):02d}"
        elif self.atr_multiple is not None:
            stop = f"ATR{float(self.atr_multiple):g}"
        else:
            stop = f"S{mode}"
        if self.target_price is not None:
            target = f"TP{float(self.target_price):.4f}"
        elif self.target_r_multiple is not None:
            target = f"R{float(self.target_r_multiple):g}"
        elif self.target_pct is not None:
            target = f"T{int(round(float(self.target_pct) * 100)):02d}"
        else:
            target = "TNONE"
        trail = str(self.trailing_exit or "NONE").upper()
        return f"{stop}_{target}_{trail}_HS{int(self.max_hold_sessions)}"


@dataclass(frozen=True)
class SwingReplayResult:
    exit_reason: str
    exit_timestamp: pd.Timestamp | None
    exit_price: float
    return_pct: float
    bars_held: int
    mfe_pct: float = np.nan
    mae_pct: float = np.nan
    r_multiple: float = np.nan
    trading_days_to_peak: float = np.nan
    calendar_days_to_peak: float = np.nan
    boundary_censored: bool = False
    right_censored: bool = False
    selection_eligible_replay: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _levels(entry: float, direction: str, rule: SwingReplayRule) -> tuple[float | None, float | None, float | None]:
    direction = _direction(direction)
    stop = float(rule.stop_price) if rule.stop_price is not None else None
    if stop is None and rule.stop_pct is not None:
        stop = entry * (1.0 - float(rule.stop_pct) if direction == "LONG" else 1.0 + float(rule.stop_pct))
    risk_pct = abs(entry - stop) / entry if stop is not None and entry > 0 else None
    target = float(rule.target_price) if rule.target_price is not None else None
    if target is None and rule.target_r_multiple is not None:
        if stop is None:
            raise ValueError("target_r_multiple requires a stop")
        risk = abs(entry - stop)
        target = entry + risk * float(rule.target_r_multiple) if direction == "LONG" else entry - risk * float(rule.target_r_multiple)
    if target is None and rule.target_pct is not None:
        target = entry * (1.0 + float(rule.target_pct) if direction == "LONG" else 1.0 - float(rule.target_pct))
    return stop, target, risk_pct


def _excursions_and_peak(window: pd.DataFrame, entry: float, direction: str, entry_date) -> tuple[float, float, float, float]:
    if window.empty:
        return np.nan, np.nan, np.nan, np.nan
    direction = _direction(direction)
    if direction == "LONG":
        highs = pd.to_numeric(window["high"], errors="coerce")
        lows = pd.to_numeric(window["low"], errors="coerce")
        peak_idx = highs.idxmax()
        mfe = (float(highs.max()) - entry) / entry
        mae = (float(lows.min()) - entry) / entry
    else:
        lows = pd.to_numeric(window["low"], errors="coerce")
        highs = pd.to_numeric(window["high"], errors="coerce")
        peak_idx = lows.idxmin()
        mfe = (entry - float(lows.min())) / entry
        mae = (entry - float(highs.max())) / entry
    peak_date = window.loc[peak_idx, "session_date"]
    future_dates = sorted({d for d in window.loc[:peak_idx, "session_date"].tolist() if d > entry_date})
    trading_days = float(len(future_dates))
    calendar_days = float((peak_date - entry_date).days)
    return float(mfe), float(mae), trading_days, calendar_days


def _censored(reason: str, *, boundary: bool = False, right: bool = False) -> SwingReplayResult:
    return SwingReplayResult(
        exit_reason=reason,
        exit_timestamp=None,
        exit_price=np.nan,
        return_pct=np.nan,
        bars_held=0,
        boundary_censored=bool(boundary),
        right_censored=bool(right),
        selection_eligible_replay=False,
    )


def _simulate_prepared_multisession_trade(
    x: pd.DataFrame,
    entry_price: float,
    entry_timestamp: Any,
    direction: str,
    rule: SwingReplayRule,
    split_end_date: Any,
    available_end_date: Any,
) -> SwingReplayResult:
    """Replay one swing rule over bars that have already been normalized once."""
    direction = _direction(direction)
    entry = float(entry_price)
    if x.empty or not np.isfinite(entry) or entry <= 0:
        return SwingReplayResult("NO_DATA", None, np.nan, np.nan, 0, selection_eligible_replay=False)
    if int(rule.max_hold_sessions) <= 0:
        raise ValueError("max_hold_sessions must be positive")

    entry_ts = _et_timestamp(entry_timestamp)
    entry_date = entry_ts.date()
    split_end = _as_date(split_end_date)
    available_end = _as_date(available_end_date)
    regular_clock = x["timestamp_et"].dt.time
    regular = x[(regular_clock >= pd.Timestamp("09:30").time()) & (regular_clock < pd.Timestamp("16:00").time())]
    followup_dates = sorted({d for d in regular["session_date"].tolist() if d > entry_date and d <= available_end})

    hold_n = int(rule.max_hold_sessions)
    if len(followup_dates) < hold_n:
        return _censored("RIGHT_CENSORED", right=True)
    terminal_date = followup_dates[hold_n - 1]
    if terminal_date > split_end:
        return _censored("BOUNDARY_CENSORED", boundary=True)
    if terminal_date > available_end:
        return _censored("RIGHT_CENSORED", right=True)

    terminal_regular = regular[regular["session_date"].eq(terminal_date)]
    if terminal_regular.empty:
        return _censored("RIGHT_CENSORED", right=True)
    terminal_ts = terminal_regular.iloc[-1]["timestamp_et"]
    path = x[(x["timestamp_et"] >= entry_ts) & (x["timestamp_et"] <= terminal_ts)].copy().reset_index(drop=True)
    if path.empty:
        return SwingReplayResult("NO_DATA", None, np.nan, np.nan, 0, selection_eligible_replay=False)

    stop, target, risk_pct = _levels(entry, direction, rule)
    seen_count = 0
    for _, row in path.iterrows():
        seen_count += 1
        open_ = float(row["open"])
        high = float(row["high"])
        low = float(row["low"])
        ts = row["timestamp_et"]
        if direction == "LONG":
            if stop is not None and open_ <= stop:
                window = path.iloc[:seen_count]
                mfe, mae, trading_peak, calendar_peak = _excursions_and_peak(window, entry, direction, entry_date)
                ret = raw_return_pct(entry, open_, direction)
                r_mult = ret / risk_pct if risk_pct else np.nan
                return SwingReplayResult("GAP_STOP", ts, open_, ret, seen_count, mfe, mae, r_mult, trading_peak, calendar_peak)
            if target is not None and open_ >= target:
                window = path.iloc[:seen_count]
                mfe, mae, trading_peak, calendar_peak = _excursions_and_peak(window, entry, direction, entry_date)
                ret = raw_return_pct(entry, target, direction)
                r_mult = ret / risk_pct if risk_pct else np.nan
                return SwingReplayResult("TARGET", ts, target, ret, seen_count, mfe, mae, r_mult, trading_peak, calendar_peak)
            stop_hit = stop is not None and low <= stop
            target_hit = target is not None and high >= target
        else:
            if stop is not None and open_ >= stop:
                window = path.iloc[:seen_count]
                mfe, mae, trading_peak, calendar_peak = _excursions_and_peak(window, entry, direction, entry_date)
                ret = raw_return_pct(entry, open_, direction)
                r_mult = ret / risk_pct if risk_pct else np.nan
                return SwingReplayResult("GAP_STOP", ts, open_, ret, seen_count, mfe, mae, r_mult, trading_peak, calendar_peak)
            if target is not None and open_ <= target:
                window = path.iloc[:seen_count]
                mfe, mae, trading_peak, calendar_peak = _excursions_and_peak(window, entry, direction, entry_date)
                ret = raw_return_pct(entry, target, direction)
                r_mult = ret / risk_pct if risk_pct else np.nan
                return SwingReplayResult("TARGET", ts, target, ret, seen_count, mfe, mae, r_mult, trading_peak, calendar_peak)
            stop_hit = stop is not None and high >= stop
            target_hit = target is not None and low <= target

        if stop_hit:
            window = path.iloc[:seen_count]
            mfe, mae, trading_peak, calendar_peak = _excursions_and_peak(window, entry, direction, entry_date)
            reason = "STOP_SAME_BAR" if target_hit else "STOP"
            ret = raw_return_pct(entry, stop, direction)
            r_mult = ret / risk_pct if risk_pct else np.nan
            return SwingReplayResult(reason, ts, float(stop), ret, seen_count, mfe, mae, r_mult, trading_peak, calendar_peak)
        if target_hit:
            window = path.iloc[:seen_count]
            mfe, mae, trading_peak, calendar_peak = _excursions_and_peak(window, entry, direction, entry_date)
            ret = raw_return_pct(entry, target, direction)
            r_mult = ret / risk_pct if risk_pct else np.nan
            return SwingReplayResult("TARGET", ts, float(target), ret, seen_count, mfe, mae, r_mult, trading_peak, calendar_peak)

    terminal = terminal_regular.iloc[-1]
    exit_price = float(terminal["close"])
    ret = raw_return_pct(entry, exit_price, direction)
    mfe, mae, trading_peak, calendar_peak = _excursions_and_peak(path, entry, direction, entry_date)
    r_mult = ret / risk_pct if risk_pct else np.nan
    return SwingReplayResult(
        "TIME", terminal["timestamp_et"], exit_price, ret, len(path),
        mfe_pct=mfe, mae_pct=mae, r_multiple=r_mult,
        trading_days_to_peak=trading_peak, calendar_days_to_peak=calendar_peak,
    )


def simulate_multisession_trade(
    bars: pd.DataFrame,
    entry_price: float,
    entry_timestamp: Any,
    direction: str,
    rule: SwingReplayRule,
    split_end_date: Any,
    available_end_date: Any,
) -> SwingReplayResult:
    return _simulate_prepared_multisession_trade(
        _prepare_bars(bars),
        entry_price,
        entry_timestamp,
        direction,
        rule,
        split_end_date,
        available_end_date,
    )


def replay_swing_signal_grid(
    bars: pd.DataFrame,
    signal: dict | pd.Series,
    rules: Iterable[SwingReplayRule],
    split_end_date: Any,
    available_end_date: Any,
) -> pd.DataFrame:
    signal_dict = signal.to_dict() if isinstance(signal, pd.Series) else dict(signal)
    prepared = _prepare_bars(bars)
    rows: list[dict[str, Any]] = []
    for rule in rules:
        result = _simulate_prepared_multisession_trade(
            prepared,
            entry_price=float(signal_dict["entry_price_slipped"]),
            entry_timestamp=signal_dict["entry_timestamp"],
            direction=str(signal_dict.get("direction", "LONG")),
            rule=rule,
            split_end_date=split_end_date,
            available_end_date=available_end_date,
        )
        rows.append({
            **signal_dict,
            "rule_id": rule.rule_id,
            "stop_mode": rule.stop_mode,
            "stop_pct": rule.stop_pct,
            "stop_price_rule": rule.stop_price,
            "atr_multiple": rule.atr_multiple,
            "target_pct": rule.target_pct,
            "target_price_rule": rule.target_price,
            "target_r_multiple": rule.target_r_multiple,
            "trailing_exit": rule.trailing_exit,
            "max_hold_sessions": rule.max_hold_sessions,
            **result.to_dict(),
        })
    return pd.DataFrame(rows)
