from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests

from scanner.core.features import prepare_intraday_bars
from scanner.core.reporting import summarize_strategy_replays
from scanner.core.validation import chronological_split
from scanner.multistrategy.config import MultiStrategyConfig
from scanner.multistrategy.study import broad_candidate_context
from scanner.portfolio.strategy_ranker import rank_strategies
from scanner.strategies.orb_stocks_in_play.strategy import generate_orb_signals
from scanner.strategies.vwap_momentum.strategy import generate_vwap_signals
from scripts.run_strategy_research import replay_signals, build_slippage_summary, summarize_peak_timing


def _block_http() -> None:
    def blocked(*args, **kwargs):
        raise RuntimeError("HTTP_DISABLED_OFFLINE_REPLAY")
    requests.sessions.Session.request = blocked


def _read_bars(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    if not df.empty and "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    return df


def _daily_prior_close(cache: Path, allowed_symbols: set[str]) -> dict[tuple[str, object], float]:
    files = sorted(cache.glob("daily_*_sip.csv.gz"))
    if not files:
        return {}
    frames = []
    for path in files:
        x = _read_bars(path)
        if not x.empty:
            x = x[x["symbol"].astype(str).isin(allowed_symbols)]
            if not x.empty:
                frames.append(x)
    if not frames:
        return {}
    daily = pd.concat(frames, ignore_index=True).drop_duplicates(["symbol", "timestamp"], keep="last")
    x = prepare_intraday_bars(daily).sort_values(["symbol", "timestamp_et"])
    x["prior_close"] = x.groupby("symbol")["close"].shift(1)
    return {
        (str(r.symbol), r.session_date): float(r.prior_close)
        for r in x.itertuples()
        if pd.notna(r.prior_close) and float(r.prior_close) > 0
    }


def _opening30_rvol_map(cache: Path, allowed_symbols: set[str], lookback: int = 20) -> dict[tuple[str, str], tuple[float, int]]:
    rows: list[dict[str, Any]] = []
    for path in sorted((cache / "early").glob("*_sip.csv.gz")):
        day = path.name.split("_sip.csv.gz")[0]
        bars = _read_bars(path)
        if bars.empty:
            continue
        bars = bars[bars["symbol"].astype(str).isin(allowed_symbols)]
        if bars.empty:
            continue
        x = prepare_intraday_bars(bars)
        clock = x["timestamp_et"].dt.time
        opening = x[(clock >= pd.Timestamp("09:30").time()) & (clock < pd.Timestamp("10:00").time())]
        if opening.empty:
            continue
        for symbol, g in opening.groupby("symbol", sort=False):
            rows.append({
                "symbol": str(symbol),
                "date": day,
                "opening30_volume": float(pd.to_numeric(g["volume"], errors="coerce").fillna(0.0).sum()),
            })
    hist = pd.DataFrame(rows)
    if hist.empty:
        return {}
    hist["date_value"] = pd.to_datetime(hist["date"], errors="coerce")
    hist = hist.sort_values(["symbol", "date_value"]).reset_index(drop=True)
    hist["prior_median"] = hist.groupby("symbol", sort=False)["opening30_volume"].transform(
        lambda s: s.shift(1).rolling(lookback, min_periods=lookback).median()
    )
    hist["history_n"] = hist.groupby("symbol", sort=False).cumcount().clip(upper=lookback)
    hist["opening_rvol"] = pd.to_numeric(hist["opening30_volume"], errors="coerce") / pd.to_numeric(hist["prior_median"], errors="coerce")
    out: dict[tuple[str, str], tuple[float, int]] = {}
    for r in hist.itertuples():
        if pd.notna(r.opening_rvol) and np.isfinite(float(r.opening_rvol)) and int(r.history_n) >= lookback:
            out[(str(r.symbol), str(r.date))] = (float(r.opening_rvol), int(r.history_n))
    return out


def main() -> None:
    _block_http()
    root = Path(".")
    cache = root / "data" / "cache" / "serclick_alpaca"
    out = root / "data" / "offline_cached_replay"
    out.mkdir(parents=True, exist_ok=True)

    minute_files = sorted((cache / "minute").glob("*_sip.csv.gz"))
    early_files = sorted((cache / "early").glob("*_sip.csv.gz"))
    if not minute_files or not early_files:
        raise RuntimeError(f"Restored cache incomplete: minute={len(minute_files)} early={len(early_files)}")

    dates = sorted({p.name.split("_sip.csv.gz")[0] for p in early_files})
    if len(dates) < 30:
        raise RuntimeError(f"Need substantial cached history; found only {len(dates)} dates")

    available_symbols_by_day: dict[str, set[str]] = {}
    cached_symbol_union: set[str] = set()
    cached_minute_symbol_days = 0
    for minute_path in minute_files:
        day = minute_path.name.split("_sip.csv.gz")[0]
        minute = _read_bars(minute_path)
        symbols = set(minute["symbol"].astype(str)) if not minute.empty else set()
        available_symbols_by_day[day] = symbols
        cached_symbol_union.update(symbols)
        cached_minute_symbol_days += len(symbols)

    cfg = MultiStrategyConfig()
    split_map = chronological_split([pd.Timestamp(d).date() for d in dates], cfg.development_sessions, cfg.validation_sessions, cfg.test_sessions)
    prior_close = _daily_prior_close(cache, cached_symbol_union)
    rvol_map = _opening30_rvol_map(cache, cached_symbol_union, cfg.opening_baseline_sessions)

    contexts: list[dict[str, Any]] = []
    restricted_broad_candidates = 0
    baseline_ready = 0

    for path in early_files:
        day = path.name.split("_sip.csv.gz")[0]
        day_symbols = available_symbols_by_day.get(day, set())
        if not day_symbols:
            continue
        bars = _read_bars(path)
        if bars.empty:
            continue
        bars = bars[bars["symbol"].astype(str).isin(day_symbols)]
        if bars.empty:
            continue
        x = prepare_intraday_bars(bars)
        d = pd.Timestamp(day).date()
        if d not in split_map:
            continue
        for symbol, g in x.groupby("symbol", sort=False):
            symbol = str(symbol)
            pc = prior_close.get((symbol, d))
            if pc is None:
                continue
            ctx = broad_candidate_context(g, pc, cfg)
            if not ctx.get("broad_candidate"):
                continue
            restricted_broad_candidates += 1
            rvol_info = rvol_map.get((symbol, day))
            if rvol_info is None:
                continue
            baseline_ready += 1
            rvol, history_n = rvol_info
            ctx.update({
                "symbol": symbol,
                "date": day,
                "split": split_map[d],
                "feed": "SIP",
                "market_cap": np.nan,
                "market_cap_bucket": "UNKNOWN",
                "opening_rvol": float(rvol),
                "opening_rvol_proxy": "OPENING30_VS_PRIOR20_OPENING30",
                "opening_rvol_history_n": int(history_n),
                "catalyst_class": "UNKNOWN",
            })
            contexts.append(ctx)

    context_df = pd.DataFrame(contexts)
    context_df.to_csv(out / "restricted_candidate_contexts.csv", index=False)
    print(f"CACHE_CONTEXTS minute_symbol_days={cached_minute_symbol_days} restricted_broad={restricted_broad_candidates} baseline_ready={baseline_ready} contexts={len(context_df)}", flush=True)

    signal_frames: list[pd.DataFrame] = []
    iterable = context_df.groupby("date", sort=True) if not context_df.empty else []
    for day, group in iterable:
        minute_path = cache / "minute" / f"{day}_sip.csv.gz"
        minute = _read_bars(minute_path)
        for context in group.to_dict("records"):
            symbol = str(context["symbol"])
            bars = minute[minute["symbol"].astype(str).eq(symbol)].copy()
            if bars.empty:
                continue
            for generator in (generate_orb_signals, generate_vwap_signals):
                signals = generator(bars, context)
                if signals.empty:
                    continue
                signals = signals.copy()
                signals["_cache_namespace"] = "serclick_alpaca"
                signals["opening_rvol_proxy"] = context["opening_rvol_proxy"]
                signal_frames.append(signals)

    signals = pd.concat(signal_frames, ignore_index=True, sort=False) if signal_frames else pd.DataFrame()
    signals.to_csv(out / "signals.csv", index=False)
    print(f"CACHE_SIGNALS rows={len(signals)}", flush=True)

    replays, replay_skips = replay_signals(root, "sip", signals)
    replays.to_csv(out / "replay_grid.csv.gz", index=False, compression="gzip")
    replay_skips.to_csv(out / "replay_skips.csv", index=False)

    summary = summarize_strategy_replays(replays)
    summary.to_csv(out / "strategy_summary.csv", index=False)
    slippage = build_slippage_summary(summary)
    slippage.to_csv(out / "slippage_summary.csv", index=False)
    peak = summarize_peak_timing(replays)
    peak.to_csv(out / "peak_timing.csv", index=False)
    leaderboard = rank_strategies(summary, min_n=5, baseline_slippage_bps=25.0) if not summary.empty else pd.DataFrame()
    leaderboard.to_csv(out / "leaderboard.csv", index=False)

    coverage = {
        "cache_mode": "SERCLICK_MINUTE_SUBSET_ONLY",
        "bias_warning": "Minute bars exist only for legacy SerClick extension-runner candidates; ORB/VWAP results are restricted real-data compatibility evidence, not an unbiased universe backtest.",
        "rvol_proxy": "Current 09:30-10:00 volume / median prior 20 cached 09:30-10:00 volumes.",
        "network": "HTTP blocked inside research process",
        "early_files": len(early_files),
        "minute_files": len(minute_files),
        "dates": len(dates),
        "cached_unique_symbols": len(cached_symbol_union),
        "cached_minute_symbol_days": int(cached_minute_symbol_days),
        "restricted_broad_candidate_symbol_days": int(restricted_broad_candidates),
        "baseline_ready_symbol_days": int(baseline_ready),
        "restricted_context_rows": int(len(context_df)),
        "signal_rows": int(len(signals)),
        "replay_rows": int(len(replays)),
        "leaderboard_rows": int(len(leaderboard)),
    }
    (out / "coverage.json").write_text(json.dumps(coverage, indent=2), encoding="utf-8")

    print("OFFLINE_CACHE_REPLAY_DONE", json.dumps(coverage), flush=True)
    if not signals.empty:
        print("SIGNAL_COUNTS", flush=True)
        print(signals.groupby(["strategy_id", "variant_id", "direction", "split"]).size().reset_index(name="n").to_string(index=False), flush=True)
    if not leaderboard.empty:
        cols = [c for c in ["strategy_id", "variant_id", "direction", "rule_id", "validation_n", "validation_profit_factor", "validation_expectancy", "validation_median_return", "test_profit_factor", "test_expectancy", "robustness_score"] if c in leaderboard.columns]
        print("LEADERBOARD", flush=True)
        print(leaderboard[cols].head(25).to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
