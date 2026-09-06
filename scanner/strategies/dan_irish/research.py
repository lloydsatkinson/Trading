from __future__ import annotations

from collections import OrderedDict
from datetime import date
from pathlib import Path
from typing import Callable, Iterable

import numpy as np
import pandas as pd

from scanner.core.multisession_replay import replay_swing_signal_grid
from scanner.core.replay import DEFAULT_SLIPPAGE_BPS, apply_entry_slippage
from scanner.core.reporting import max_drawdown, profit_factor, summarize_censoring, summarize_strategy_replays, summarize_swing_holds
from scanner.core.features import prepare_intraday_bars
from .config import (
    DanConfig,
    IMPULSE_GRID,
    PULLBACK_DEPTH_GRID,
    RETAINED_GAIN_GRID,
    TURNOVER_GRID,
)
from .intraday import generate_dan_intraday_signal_grid
from .rules import default_dan_swing_rules
from .swing import generate_dan_swing_signals

MinuteCacheLoader = Callable[[Path, str, str, str, str], pd.DataFrame]
DayMinuteLoader = Callable[[Path, str, str, str], pd.DataFrame]


def make_cached_symbol_minute_loader(
    day_loader: DayMinuteLoader,
    max_days: int = 24,
) -> MinuteCacheLoader:
    """Bound full-day minute decompression to once per recently used cache key."""
    limit = int(max_days)
    if limit <= 0:
        raise ValueError("max_days must be positive")
    cache: OrderedDict[tuple[str, str, str, str], dict[str, pd.DataFrame]] = OrderedDict()

    def load(root: Path, namespace: str, day: str, feed: str, symbol: str) -> pd.DataFrame:
        key = (str(Path(root)), str(namespace), str(day), str(feed).lower())
        if key in cache:
            by_symbol = cache.pop(key)
            cache[key] = by_symbol
        else:
            frame = day_loader(Path(root), str(namespace), str(day), str(feed))
            by_symbol: dict[str, pd.DataFrame] = {}
            if frame is not None and not frame.empty and "symbol" in frame.columns:
                symbols = frame["symbol"].astype(str)
                for value in symbols.unique():
                    by_symbol[str(value)] = frame.loc[symbols.eq(str(value))].copy()
            cache[key] = by_symbol
            while len(cache) > limit:
                cache.popitem(last=False)
        selected = by_symbol.get(str(symbol))
        return selected.copy() if selected is not None else pd.DataFrame()

    return load


def run_study_with_optional_dan(study, *, needs_price_volume: bool, needs_dan: bool) -> dict:
    # needs_price_volume remains part of the runner-facing contract, but native
    # study discovery now handles the union of broad and Dan candidates in one pass.
    _ = needs_price_volume
    return study.run(include_dan_candidates=True) if needs_dan else study.run()


def _daily_dates_by_symbol(daily_bars: pd.DataFrame) -> dict[str, list[date]]:
    if daily_bars.empty:
        return {}
    x = prepare_intraday_bars(daily_bars)
    if x.empty or "symbol" not in x.columns:
        return {}
    return {
        str(symbol): sorted(set(group["session_date"].tolist()))
        for symbol, group in x.groupby(x["symbol"].astype(str), sort=False)
    }


def _daily_dates_for_symbol(daily_bars: pd.DataFrame, symbol: str) -> list[date]:
    return _daily_dates_by_symbol(daily_bars).get(str(symbol), [])


def ensure_dan_followup_caches(study, contexts: pd.DataFrame, daily_bars: pd.DataFrame, cfg: DanConfig | None = None) -> None:
    cfg = cfg or DanConfig()
    if contexts.empty or daily_bars.empty:
        return
    daily_dates_by_symbol = _daily_dates_by_symbol(daily_bars)
    symbols_by_day: dict[date, set[str]] = {}
    for context in contexts.to_dict("records"):
        symbol = str(context["symbol"])
        day0 = pd.Timestamp(context["date"]).date()
        later = [day for day in daily_dates_by_symbol.get(symbol, []) if day > day0][: int(cfg.followup_sessions)]
        for day in later:
            symbols_by_day.setdefault(day, set()).add(symbol)
    for day in sorted(symbols_by_day):
        study.ensure_minute_day(sorted(symbols_by_day[day]), day)


def generate_dan_signal_set(
    root: str | Path,
    feed: str,
    study,
    meta: dict,
    minute_loader: MinuteCacheLoader,
    cfg: DanConfig | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    cfg = cfg or DanConfig()
    root = Path(root)
    contexts = meta.get("dan_candidate_contexts", pd.DataFrame())
    daily_bars = meta.get("daily_bars", pd.DataFrame())
    session_splits = meta.get("session_splits", {})
    if contexts is None or contexts.empty:
        return pd.DataFrame(), pd.DataFrame()

    prepared_daily = (
        daily_bars.copy()
        if not daily_bars.empty and {"timestamp_et", "session_date"}.issubset(daily_bars.columns)
        else prepare_intraday_bars(daily_bars)
    )
    ensure_dan_followup_caches(study, contexts, prepared_daily, cfg)
    daily_by_symbol = (
        {
            str(symbol): group.copy()
            for symbol, group in prepared_daily.groupby(prepared_daily["symbol"].astype(str), sort=False)
        }
        if not prepared_daily.empty and "symbol" in prepared_daily.columns
        else {}
    )
    frames: list[pd.DataFrame] = []
    skips: list[dict] = []

    def load_symbol_minutes(symbol: str, day: date) -> pd.DataFrame:
        bars = minute_loader(root, "multistrategy_alpaca", str(day), feed, symbol)
        return bars

    for context in contexts.to_dict("records"):
        symbol = str(context["symbol"])
        day = str(context["date"])
        day0_bars = minute_loader(root, "multistrategy_alpaca", day, feed, symbol)
        if day0_bars.empty:
            skips.append({"symbol": symbol, "date": day, "reason": "MISSING_DAN_DAY0_MINUTE_CACHE"})
            continue

        intraday = generate_dan_intraday_signal_grid(day0_bars, context, cfg)
        if not intraday.empty:
            intraday = intraday.copy()
            intraday["_cache_namespace"] = "multistrategy_alpaca"
            frames.append(intraday)

        swing = generate_dan_swing_signals(
            context,
            daily_by_symbol.get(symbol, pd.DataFrame()),
            load_symbol_minutes,
            cfg,
            session_splits=session_splits,
        )
        if not swing.empty:
            swing = swing.copy()
            swing["_cache_namespace"] = "multistrategy_alpaca"
            frames.append(swing)

        if intraday.empty and swing.empty:
            skips.append({"symbol": symbol, "date": day, "reason": "NO_DAN_SIGNAL"})

    return (
        pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame(),
        pd.DataFrame(skips),
    )


def replay_dan_swing_signals(
    root: str | Path,
    feed: str,
    signals: pd.DataFrame,
    daily_bars: pd.DataFrame,
    split_end_dates: dict[str, str],
    minute_loader: MinuteCacheLoader,
    slippage_bps: Iterable[float] = DEFAULT_SLIPPAGE_BPS,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if signals.empty:
        return pd.DataFrame(), pd.DataFrame()
    root = Path(root)
    complete_daily_dates = _daily_dates_by_symbol(daily_bars)
    daily_dates_by_symbol = {
        symbol: complete_daily_dates.get(symbol, [])
        for symbol in signals["symbol"].astype(str).unique()
    }
    all_dates = sorted({d for dates in daily_dates_by_symbol.values() for d in dates})
    available_end = max(all_dates) if all_dates else None
    if available_end is None:
        return pd.DataFrame(), pd.DataFrame([{"reason": "NO_DAILY_FOLLOWUP_DATA"}])

    frames: list[pd.DataFrame] = []
    skips: list[dict] = []
    for signal in signals.to_dict("records"):
        symbol = str(signal["symbol"])
        entry_date = pd.Timestamp(signal["entry_timestamp"]).date()
        probe_rules = default_dan_swing_rules(signal)
        max_hold_sessions = max((int(rule.max_hold_sessions) for rule in probe_rules), default=0)
        relevant_dates = [d for d in daily_dates_by_symbol.get(symbol, []) if d >= entry_date][
            : max_hold_sessions + 1
        ]
        minute_frames: list[pd.DataFrame] = []
        missing_dates: list[date] = []
        for day in relevant_dates:
            bars = minute_loader(root, "multistrategy_alpaca", str(day), feed, symbol)
            if bars.empty:
                missing_dates.append(day)
            else:
                minute_frames.append(bars)
        if missing_dates:
            for missing_day in missing_dates:
                skips.append({
                    "symbol": symbol,
                    "date": signal.get("date"),
                    "reason": "MISSING_DAN_SWING_SESSION_CACHE",
                    "missing_session": str(missing_day),
                })
            continue
        path = pd.concat(minute_frames, ignore_index=True, sort=False) if minute_frames else pd.DataFrame()
        if path.empty:
            skips.append({"symbol": symbol, "date": signal.get("date"), "reason": "MISSING_DAN_SWING_REPLAY_CACHE"})
            continue

        split = str(signal.get("split") or "forward")
        split_end = split_end_dates.get(split, str(available_end))
        for bps in slippage_bps:
            priced = dict(signal)
            raw = float(priced["entry_price_raw"])
            priced["entry_price_slipped"] = apply_entry_slippage(raw, str(priced.get("direction", "LONG")), float(bps))
            priced["slippage_bps"] = float(bps)
            rules = default_dan_swing_rules(priced)
            replay = replay_swing_signal_grid(
                path,
                priced,
                rules,
                split_end_date=split_end,
                available_end_date=str(available_end),
            )
            if not replay.empty:
                frames.append(replay)
    return (
        pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame(),
        pd.DataFrame(skips),
    )


def persist_dan_rule_identity(replays: pd.DataFrame) -> pd.DataFrame:
    """Persist setup + exit-rule identity so exported rows cannot be pooled accidentally."""
    if replays.empty:
        return replays.copy()
    x = replays.copy()
    if "setup_id" not in x.columns or "rule_id" not in x.columns:
        return x
    if "exit_rule_id" not in x.columns:
        x["exit_rule_id"] = x["rule_id"].astype(str)
    else:
        missing = x["exit_rule_id"].isna()
        x.loc[missing, "exit_rule_id"] = x.loc[missing, "rule_id"].astype(str)
    setup = x["setup_id"].astype(str)
    exit_rule = x["exit_rule_id"].astype(str)
    x["rule_id"] = setup + "__" + exit_rule
    return x


def summarize_dan_threshold_grid(replays: pd.DataFrame) -> pd.DataFrame:
    """Evaluate approved continuous Dan cuts for non-empty, complete replay groups.

    The output is intentionally sparse: threshold combinations with zero qualifying
    trades are omitted. This preserves full auditability without materialising
    millions of empty rows.
    """
    if replays.empty:
        return pd.DataFrame()
    x = persist_dan_rule_identity(replays)
    if "selection_eligible_replay" in x.columns:
        x = x.loc[x["selection_eligible_replay"].fillna(True).astype(bool)].copy()
    if x.empty:
        return pd.DataFrame()

    required = {
        "strategy_id", "variant_id", "setup_id", "rule_id", "split",
        "slippage_bps", "impulse_pct", "pm_dollar_turnover", "return_pct",
    }
    if not required.issubset(x.columns):
        return pd.DataFrame()

    x["_retained"] = pd.to_numeric(
        x["retained_gain_ratio"] if "retained_gain_ratio" in x.columns else pd.Series(np.nan, index=x.index),
        errors="coerce",
    )
    if "day0_retained_gain" in x.columns:
        swing_retained = pd.to_numeric(x["day0_retained_gain"], errors="coerce")
        x["_retained"] = x["_retained"].where(x["_retained"].notna(), swing_retained)
    x["_pullback"] = pd.to_numeric(
        x["pullback_depth"] if "pullback_depth" in x.columns else pd.Series(np.nan, index=x.index),
        errors="coerce",
    )
    x["_impulse"] = pd.to_numeric(x["impulse_pct"], errors="coerce")
    x["_turnover"] = pd.to_numeric(x["pm_dollar_turnover"], errors="coerce")
    x["_return"] = pd.to_numeric(x["return_pct"], errors="coerce")
    x["_r"] = pd.to_numeric(
        x["r_multiple"] if "r_multiple" in x.columns else pd.Series(np.nan, index=x.index),
        errors="coerce",
    )
    x = x.dropna(subset=["_impulse", "_turnover", "_retained", "_pullback", "_return"])
    if x.empty:
        return pd.DataFrame()

    dims = ["strategy_id", "variant_id", "setup_id", "rule_id", "split", "slippage_bps"]
    rows: list[dict] = []
    for keys, group in x.groupby(dims, dropna=False, sort=False):
        keys = keys if isinstance(keys, tuple) else (keys,)
        identity = dict(zip(dims, keys))
        for impulse_cut in IMPULSE_GRID:
            impulse = group[group["_impulse"] >= float(impulse_cut)]
            if impulse.empty:
                continue
            for turnover_cut in TURNOVER_GRID:
                turnover = impulse[impulse["_turnover"] >= float(turnover_cut)]
                if turnover.empty:
                    continue
                for retained_cut in RETAINED_GAIN_GRID:
                    retained = turnover[turnover["_retained"] >= float(retained_cut)]
                    if retained.empty:
                        continue
                    for pullback_cut in PULLBACK_DEPTH_GRID:
                        selected = retained[retained["_pullback"] <= float(pullback_cut)]
                        if selected.empty:
                            continue
                        returns = selected["_return"].dropna()
                        if returns.empty:
                            continue
                        r_values = selected["_r"].dropna()
                        rows.append({
                            **identity,
                            "min_impulse_pct": float(impulse_cut),
                            "min_dollar_turnover": float(turnover_cut),
                            "min_retained_gain": float(retained_cut),
                            "max_pullback_depth": float(pullback_cut),
                            "n": int(len(returns)),
                            "win_rate": float((returns > 0).mean()),
                            "expectancy": float(returns.mean()),
                            "profit_factor": profit_factor(returns),
                            "mean_r": float(r_values.mean()) if not r_values.empty else np.nan,
                            "max_drawdown": max_drawdown(returns),
                        })
    return pd.DataFrame(rows)


def retained_gain_bucket(value) -> str:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return "UNKNOWN"
    if not np.isfinite(x):
        return "UNKNOWN"
    if x < 0.40:
        return "LT_40"
    if x < 0.50:
        return "40_TO_50"
    if x < 0.65:
        return "50_TO_65"
    if x < 0.80:
        return "65_TO_80"
    return "GE_80"


def add_retained_gain_bucket(replays: pd.DataFrame) -> pd.DataFrame:
    if replays.empty:
        return replays.copy()
    x = replays.copy()
    intraday = pd.to_numeric(x.get("retained_gain_ratio"), errors="coerce") if "retained_gain_ratio" in x.columns else pd.Series(np.nan, index=x.index)
    swing = pd.to_numeric(x.get("day0_retained_gain"), errors="coerce") if "day0_retained_gain" in x.columns else pd.Series(np.nan, index=x.index)
    combined = intraday.where(intraday.notna(), swing)
    x["retained_gain_bucket"] = combined.map(retained_gain_bucket)
    return x


def overnight_gap_risk_summary(swing_replays: pd.DataFrame, baseline_slippage_bps: float = 25.0) -> pd.DataFrame:
    if swing_replays.empty:
        return pd.DataFrame()
    x = swing_replays.copy()
    if "selection_eligible_replay" in x.columns:
        eligible = x["selection_eligible_replay"].fillna(True).astype(bool)
        x = x.loc[eligible].copy()
    if "slippage_bps" in x.columns:
        x = x[pd.to_numeric(x["slippage_bps"], errors="coerce").eq(float(baseline_slippage_bps))]
    if x.empty:
        return pd.DataFrame()
    dims = [c for c in (
        "strategy_id",
        "variant_id",
        "setup_id",
        "rule_id",
        "max_hold_sessions",
        "split",
        "price_bucket",
        "market_cap_bucket",
    ) if c in x.columns]
    rows = []
    for keys, group in x.groupby(dims, dropna=False, sort=False):
        keys = keys if isinstance(keys, tuple) else (keys,)
        if "gap_through_stop" in group.columns:
            gap = group["gap_through_stop"].fillna(False).astype(bool)
        elif "exit_reason" in group.columns:
            gap = group["exit_reason"].astype(str).eq("GAP_STOP")
        else:
            gap = pd.Series(False, index=group.index)
        gap_returns = pd.to_numeric(group.loc[gap, "return_pct"], errors="coerce").dropna()
        rows.append({
            **dict(zip(dims, keys)),
            "replays_n": int(len(group)),
            "gap_stop_n": int(gap.sum()),
            "gap_stop_rate": float(gap.mean()) if len(group) else np.nan,
            "mean_gap_stop_return": float(gap_returns.mean()) if not gap_returns.empty else np.nan,
            "worst_gap_stop_return": float(gap_returns.min()) if not gap_returns.empty else np.nan,
        })
    return pd.DataFrame(rows)


def build_dan_summaries(replays: pd.DataFrame, swing_replays: pd.DataFrame) -> dict[str, pd.DataFrame]:
    enriched = add_retained_gain_bucket(replays)
    return {
        "enriched_replays": enriched,
        "price_bucket_summary": summarize_strategy_replays(enriched, segment_cols=("price_bucket",)) if not enriched.empty else pd.DataFrame(),
        "retained_gain_summary": summarize_strategy_replays(enriched, segment_cols=("retained_gain_bucket",)) if not enriched.empty else pd.DataFrame(),
        "swing_hold_summary": summarize_swing_holds(swing_replays) if not swing_replays.empty else pd.DataFrame(),
        "overnight_gap_risk": overnight_gap_risk_summary(swing_replays),
        "censor_summary": summarize_censoring(swing_replays) if not swing_replays.empty else pd.DataFrame(),
    }
