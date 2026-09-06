from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from scanner.core.features import prepare_intraday_bars
from scanner.core.models import market_cap_bucket
from scanner.core.validation import chronological_split
from scanner.multistrategy.study import dan_candidate_context, opening5_row, opening_baseline_for_day
from .config import DanConfig


def _split_end_dates(split_map: dict[date, str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for day, split in split_map.items():
        current = out.get(str(split))
        if current is None or day > pd.Timestamp(current).date():
            out[str(split)] = str(day)
    return out


def run_dan_candidate_study(study, cfg: DanConfig | None = None) -> dict[str, Any]:
    """Run Dan-only candidate discovery using the existing multistrategy caches.

    This adapter keeps the current ORB/VWAP `MultiStrategyStudy.run()` semantics
    untouched while reusing its universe, daily, early-session, opening-history,
    market-cap and manifest-backed minute-cache machinery for the wider Dan price
    universe. It can be retired later if `MultiStrategyStudy.run()` grows a native
    `include_dan_candidates` argument; the runner already supports that shape.
    """
    cfg = cfg or DanConfig()
    sessions = study._completed_sessions()
    split_map = chronological_split(
        sessions,
        study.cfg.development_sessions,
        study.cfg.validation_sessions,
        study.cfg.test_sessions,
    )
    assets = study._assets()
    symbols = assets["symbol"].tolist() if not assets.empty and "symbol" in assets.columns else []
    daily = study._daily_bars(symbols, sessions)
    prior_close = study._prior_close_map(daily)
    contexts: list[dict[str, Any]] = []
    minute_files: list[str] = []

    for day in sessions:
        early = study._fetch_early_day(symbols, day)
        if early.empty:
            continue
        early = prepare_intraday_bars(early)
        day_contexts: list[dict[str, Any]] = []
        for symbol, group in early.groupby("symbol", sort=False):
            pc = prior_close.get((str(symbol), day))
            if pc is None:
                continue
            ctx = dan_candidate_context(group, pc, cfg)
            if not ctx.get("dan_candidate"):
                continue
            ctx.update({
                "symbol": str(symbol),
                "date": str(day),
                "split": split_map[day],
                "feed": study.feed.upper(),
            })
            day_contexts.append(ctx)
        if not day_contexts:
            continue

        from scanner.serclick.marketcap import load_or_fetch_market_cap_snapshot

        snapshot = load_or_fetch_market_cap_snapshot(study.paths.root, day)
        cap_map: dict[str, dict[str, Any]] = {}
        if snapshot is not None and not snapshot.empty:
            for record in snapshot.to_dict("records"):
                cap_map[str(record.get("symbol", "")).upper()] = record
        for ctx in day_contexts:
            cap_row = cap_map.get(str(ctx["symbol"]).upper(), {})
            cap = cap_row.get("market_cap", np.nan)
            ctx["market_cap"] = cap
            ctx["market_cap_bucket"] = market_cap_bucket(cap)
            ctx["market_cap_source"] = cap_row.get("market_cap_source")
            ctx["market_cap_asof"] = cap_row.get("market_cap_asof")

        candidate_symbols = sorted({str(row["symbol"]) for row in day_contexts})
        opening_history = study._fetch_opening_history(candidate_symbols, sessions, day)
        minute = study.ensure_minute_day(candidate_symbols, day)
        minute_cache = study.paths.cache / "minute" / f"{day}_{study.feed}.csv.gz"
        minute_files.append(str(minute_cache))

        for ctx in day_contexts:
            symbol = str(ctx["symbol"])
            symbol_bars = minute[minute["symbol"].astype(str).eq(symbol)].copy() if not minute.empty else pd.DataFrame()
            current = opening5_row(symbol_bars, symbol, day) if not symbol_bars.empty else {
                "opening5_volume": np.nan,
                "opening5_dollar_turnover": np.nan,
            }
            baseline = opening_baseline_for_day(
                opening_history,
                symbol,
                day,
                study.cfg.opening_baseline_sessions,
            )
            median_volume = baseline["median_opening5_volume"]
            ctx.update(current)
            ctx.update(baseline)
            ctx["opening_rvol"] = (
                float(current["opening5_volume"] / median_volume)
                if np.isfinite(current["opening5_volume"])
                and np.isfinite(median_volume)
                and median_volume > 0
                else np.nan
            )
            contexts.append(ctx)

    output_dir = study.paths.output / study.run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    context_df = pd.DataFrame(contexts)
    context_df.to_csv(output_dir / "dan_candidate_contexts.csv", index=False)
    return {
        "run_id": study.run_id,
        "feed": study.feed.upper(),
        "sessions": len(sessions),
        "start_date": str(sessions[0]),
        "end_date": str(sessions[-1]),
        "candidate_contexts": pd.DataFrame(),
        "dan_candidate_contexts": context_df,
        "daily_bars": daily,
        "split_end_dates": _split_end_dates(split_map),
        "minute_files": minute_files,
        "output_dir": str(output_dir),
    }
