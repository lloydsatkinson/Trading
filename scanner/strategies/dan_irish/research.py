from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Callable, Iterable

import numpy as np
import pandas as pd

from scanner.core.multisession_replay import replay_swing_signal_grid
from scanner.core.replay import DEFAULT_SLIPPAGE_BPS, apply_entry_slippage
from scanner.core.reporting import summarize_censoring, summarize_strategy_replays, summarize_swing_holds
from scanner.core.features import prepare_intraday_bars
from .config import DanConfig
from .intraday import generate_dan_intraday_signals
from .rules import default_dan_swing_rules
from .swing import generate_dan_swing_signals

MinuteCacheLoader = Callable[[Path, str, str, str, str], pd.DataFrame]


def run_study_with_optional_dan(study, *, needs_price_volume: bool, needs_dan: bool) -> dict:
    # needs_price_volume remains part of the runner-facing contract, but native
    # study discovery now handles the union of broad and Dan candidates in one pass.
    _ = needs_price_volume
    return study.run(include_dan_candidates=True) if needs_dan else study.run()


def _daily_dates_for_symbol(daily_bars: pd.DataFrame, symbol: str) -> list[date]:
    if daily_bars.empty:
        return []
    x = prepare_intraday_bars(daily_bars)
    x = x[x["symbol"].astype(str).eq(str(symbol))]
    return sorted(set(x["session_date"].tolist()))


def ensure_dan_followup_caches(study, contexts: pd.DataFrame, daily_bars: pd.DataFrame, cfg: DanConfig | None = None) -> None:
    cfg = cfg or DanConfig()
    if contexts.empty or daily_bars.empty:
        return
    ensured: set[tuple[str, date]] = set()
    for context in contexts.to_dict("records"):
        symbol = str(context["symbol"])
        day0 = pd.Timestamp(context["date"]).date()
        later = [day for day in _daily_dates_for_symbol(daily_bars, symbol) if day > day0][: int(cfg.followup_sessions)]
        for day in later:
            key = (symbol, day)
            if key in ensured:
                continue
            study.ensure_minute_day([symbol], day)
            ensured.add(key)


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

    ensure_dan_followup_caches(study, contexts, daily_bars, cfg)
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

        intraday = generate_dan_intraday_signals(day0_bars, context, cfg)
        if not intraday.empty:
            intraday = intraday.copy()
            intraday["_cache_namespace"] = "multistrategy_alpaca"
            frames.append(intraday)

        swing = generate_dan_swing_signals(
            context,
            daily_bars,
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
    daily_dates_by_symbol = {
        symbol: _daily_dates_for_symbol(daily_bars, symbol)
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
        relevant_dates = [d for d in daily_dates_by_symbol.get(symbol, []) if d >= entry_date]
        minute_frames: list[pd.DataFrame] = []
        for day in relevant_dates:
            bars = minute_loader(root, "multistrategy_alpaca", str(day), feed, symbol)
            if not bars.empty:
                minute_frames.append(bars)
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
        gap = group["exit_reason"].astype(str).eq("GAP_STOP") if "exit_reason" in group.columns else pd.Series(False, index=group.index)
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
