from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable

import numpy as np
import pandas as pd

ET = "America/New_York"
DEFAULT_SLIPPAGE_BPS = (10, 25, 50, 75, 100)
DEFAULT_MAX_HOLDS = (5, 10, 15, 30, 45, 60, 90, 120)


def _direction(value: str) -> str:
    direction = str(value).upper()
    if direction not in {"LONG", "SHORT"}:
        raise ValueError("direction must be LONG or SHORT")
    return direction


def _et_timestamp(value: Any) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize(ET)
    return ts.tz_convert(ET)


def raw_return_pct(entry_price: float, exit_price: float, direction: str) -> float:
    direction = _direction(direction)
    entry = float(entry_price)
    exit_ = float(exit_price)
    if not np.isfinite(entry) or entry <= 0 or not np.isfinite(exit_):
        return np.nan
    if direction == "LONG":
        return (exit_ - entry) / entry
    return (entry - exit_) / entry


def apply_entry_slippage(price: float, direction: str, bps: float) -> float:
    direction = _direction(direction)
    price = float(price)
    fraction = float(bps) / 10_000.0
    slipped = price * (1.0 + fraction if direction == "LONG" else 1.0 - fraction)
    return round(slipped, 12)


@dataclass(frozen=True)
class ReplayRule:
    stop_pct: float | None = None
    target_pct: float | None = None
    max_hold_minutes: int | None = 60
    stop_price: float | None = None
    target_price: float | None = None
    target_r_multiple: float | None = None
    hold_to_eod: bool = False

    @property
    def rule_id(self) -> str:
        stop = f"SP{self.stop_price:.4f}" if self.stop_price is not None else f"S{int(round((self.stop_pct or 0) * 100)):02d}"
        if self.target_price is not None:
            target = f"TP{self.target_price:.4f}"
        elif self.target_r_multiple is not None:
            target = f"R{self.target_r_multiple:g}"
        else:
            target = f"T{int(round((self.target_pct or 0) * 100)):02d}"
        hold = "EOD" if self.hold_to_eod else f"H{self.max_hold_minutes}"
        return f"{stop}_{target}_{hold}"


@dataclass(frozen=True)
class ReplayResult:
    exit_reason: str
    exit_timestamp: pd.Timestamp | None
    exit_price: float
    return_pct: float
    bars_held: int
    mfe_pct: float = np.nan
    mae_pct: float = np.nan
    r_multiple: float = np.nan

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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
    for column in ("open", "high", "low", "close"):
        x[column] = pd.to_numeric(x[column], errors="coerce")
    return x.sort_values("timestamp_et").reset_index(drop=True)


def _levels(entry_price: float, direction: str, rule: ReplayRule) -> tuple[float | None, float | None, float | None]:
    direction = _direction(direction)
    entry = float(entry_price)
    stop = rule.stop_price
    if stop is None and rule.stop_pct is not None:
        stop = entry * (1.0 - rule.stop_pct if direction == "LONG" else 1.0 + rule.stop_pct)
    target = rule.target_price
    risk_pct = None
    if stop is not None:
        risk_pct = abs(entry - float(stop)) / entry
    if target is None and rule.target_r_multiple is not None:
        if stop is None:
            raise ValueError("target_r_multiple requires a stop level")
        risk_dollars = abs(entry - float(stop))
        target = entry + risk_dollars * rule.target_r_multiple if direction == "LONG" else entry - risk_dollars * rule.target_r_multiple
    if target is None and rule.target_pct is not None:
        target = entry * (1.0 + rule.target_pct if direction == "LONG" else 1.0 - rule.target_pct)
    return (float(stop) if stop is not None else None, float(target) if target is not None else None, risk_pct)


def _excursions(x: pd.DataFrame, entry: float, direction: str) -> tuple[float, float]:
    if x.empty:
        return np.nan, np.nan
    if direction == "LONG":
        mfe = (float(x["high"].max()) - entry) / entry
        mae = (float(x["low"].min()) - entry) / entry
    else:
        mfe = (entry - float(x["low"].min())) / entry
        mae = (entry - float(x["high"].max())) / entry
    return mfe, mae


def simulate_trade(
    bars: pd.DataFrame,
    entry_price: float,
    entry_timestamp: Any,
    direction: str,
    rule: ReplayRule,
    session_end: str = "16:00",
) -> ReplayResult:
    direction = _direction(direction)
    entry = float(entry_price)
    if bars.empty or not np.isfinite(entry) or entry <= 0:
        return ReplayResult("NO_DATA", None, np.nan, np.nan, 0)
    x = _prepare_bars(bars)
    entry_ts = _et_timestamp(entry_timestamp)
    x = x[x["timestamp_et"] >= entry_ts].copy()
    if rule.hold_to_eod:
        hour, minute = [int(part) for part in session_end.split(":", 1)]
        end_ts = entry_ts.normalize() + pd.Timedelta(hours=hour, minutes=minute)
        x = x[x["timestamp_et"] <= end_ts]
        terminal_reason = "EOD"
    else:
        if rule.max_hold_minutes is None or rule.max_hold_minutes <= 0:
            raise ValueError("max_hold_minutes must be positive unless hold_to_eod is true")
        end_ts = entry_ts + pd.Timedelta(minutes=rule.max_hold_minutes)
        x = x[x["timestamp_et"] <= end_ts]
        terminal_reason = "TIME"
    if x.empty:
        return ReplayResult("NO_DATA", None, np.nan, np.nan, 0)

    stop, target, risk_pct = _levels(entry, direction, rule)
    seen_rows: list[int] = []
    for idx, row in x.iterrows():
        seen_rows.append(idx)
        low = float(row["low"])
        high = float(row["high"])
        ts = row["timestamp_et"]
        if direction == "LONG":
            stop_hit = stop is not None and low <= stop
            target_hit = target is not None and high >= target
        else:
            stop_hit = stop is not None and high >= stop
            target_hit = target is not None and low <= target
        window = x.loc[seen_rows]
        mfe, mae = _excursions(window, entry, direction)
        if stop_hit:
            reason = "STOP_SAME_BAR" if target_hit else "STOP"
            ret = raw_return_pct(entry, stop, direction)
            r_mult = ret / risk_pct if risk_pct else np.nan
            return ReplayResult(reason, ts, stop, ret, len(seen_rows), mfe, mae, r_mult)
        if target_hit:
            ret = raw_return_pct(entry, target, direction)
            r_mult = ret / risk_pct if risk_pct else np.nan
            return ReplayResult("TARGET", ts, target, ret, len(seen_rows), mfe, mae, r_mult)

    last = x.iloc[-1]
    exit_price = float(last["close"])
    ret = raw_return_pct(entry, exit_price, direction)
    mfe, mae = _excursions(x, entry, direction)
    r_mult = ret / risk_pct if risk_pct else np.nan
    return ReplayResult(terminal_reason, last["timestamp_et"], exit_price, ret, len(x), mfe, mae, r_mult)


def replay_signal_grid(
    bars: pd.DataFrame,
    signal: dict | pd.Series,
    rules: Iterable[ReplayRule],
    session_end: str = "16:00",
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    signal_dict = signal.to_dict() if isinstance(signal, pd.Series) else dict(signal)
    direction = signal_dict.get("direction", "LONG")
    entry_price = float(signal_dict["entry_price_slipped"])
    entry_timestamp = signal_dict["entry_timestamp"]
    for rule in rules:
        result = simulate_trade(bars, entry_price, entry_timestamp, direction, rule, session_end=session_end)
        rows.append({
            **signal_dict,
            "rule_id": rule.rule_id,
            "stop_pct": rule.stop_pct,
            "target_pct": rule.target_pct,
            "max_hold_minutes": rule.max_hold_minutes,
            "stop_price_rule": rule.stop_price,
            "target_price_rule": rule.target_price,
            "target_r_multiple": rule.target_r_multiple,
            "hold_to_eod": rule.hold_to_eod,
            **result.to_dict(),
        })
    return pd.DataFrame(rows)
