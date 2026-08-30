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


def _daily_prior_close(cache: Path) -> dict[tuple[str, object], float]:
    files = sorted(cache.glob("daily_*_sip.csv.gz"))
    if not files:
        return {}
    frames = [_read_bars(p) for p in files]
    daily = pd.concat([x for x in frames if not x.empty], ignore_index=True)
    if daily.empty:
        return {}
    daily = daily.drop_duplicates(["symbol", "timestamp"], keep="last")
    x = prepare_intraday_bars(daily).sort_values(["symbol", "timestamp_et"])
    x["prior_close"] = x.groupby("symbol")["close"].shift(1)
    return {
        (str(r.symbol), r.session_date): float(r.prior_close)
        for r in x.itertuples()
        if pd.notna(r.prior_close) and float(r.prior_close) > 0
    }


def _opening30_history(cache: Path) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for path in sorted((cache / "early").glob("*_sip.csv.gz")):
        day = path.name.split("_sip.csv.gz")[0]
        bars = _read_bars(path)
        if bars.empty:
            continue
        x = prepare_intraday_bars(bars)
        clock = x["timestamp_et"].dt.time
        opening = x[(clock >= pd.Timestamp("09:30").time()) & (clock < pd.Timestamp("10:00").time())]
        if opening.empty:
            continue
        for symbol, g in opening.groupby("symbol", sort=False):
            typical = (pd.to_numeric(g["high"], errors="coerce") + pd.to_numeric(g["low"], errors="coerce") + pd.to_numeric(g["close"], errors="coerce")) / 3.0
            volume = pd.to_numeric(g["volume"], errors="coerce").fillna(0.0)
            rows.append({
                "symbol": str(symbol),
                "date": day,
                "opening30_volume": float(volume.sum()),
                "opening30_dollar_turnover": float((volume * typical.fillna(g["close"])).sum()),
            })
    return pd.DataFrame(rows)


def _rvol_proxy(history: pd.DataFrame, symbol: str, day: str, lookback: int = 20) -> tuple[float | None, int]:
    if history.empty:
        return None, 0
    target = pd.Timestamp(day).date()
    x = history[history["symbol"].astype(str).eq(str(symbol))].copy()
    x["date_value"] = pd.to_datetime(x["date"], errors="coerce").dt.date
    current = x[x["date_value"].eq(target)]
    prior = x[x["date_value"].lt(target)].sort_values("date_value").tail(lookback)
    if current.empty or len(prior) < lookback:
        return None, len(prior)
    cur = float(pd.to_numeric(current["opening30_volume"], errors="coerce").iloc[-1])
    med = float(pd.to_numeric(prior["opening30_volume"], errors="coerce").median())
    if not np.isfinite(cur) or not np.isfinite(med) or med <= 0:
        return None, len(prior)
    return cur / med, len(prior)


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

    cfg = MultiStrategyConfig()
    split_map = chronological_split([pd.Timestamp(d).date() for d in dates], cfg.development_sessions, cfg.validation_sessions, cfg.test_sessions)
    prior_close = _daily_prior_close(cache)
    opening_history = _opening30_history(cache)

    contexts: list[dict[str, Any]] = []
    broad_total = 0
    broad_with_minute = 0
    baseline_ready = 0
    available_symbols_by_day: dict[str, set[str]] = {}

    for minute_path in minute_files:
        day = minute_path.name.split("_sip.csv.gz")[0]
        minute = _read_bars(minute_path)
        available_symbols_by_day[day] = set(minute["symbol"].astype(str)) if not minute.empty else set()

    for path in early_files:
        day = path.name.split("_sip.csv.gz")[0]
        bars = _read_bars(path)
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
            broad_total += 1
            rvol, history_n = _rvol_proxy(opening_history, symbol, day, cfg.opening_baseline_sessions)
            if rvol is None:
                continue
            baseline_ready += 1
            if symbol not in available_symbols_by_day.get(day, set()):
                continue
            broad_with_minute += 1
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

    signal_frames: list[pd.DataFrame] = []
    for day, group in context_df.groupby("date", sort=True) if not context_df.empty else []:
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
        "broad_candidate_symbol_days": broad_total,
        "baseline_ready_symbol_days": baseline_ready,
        "broad_candidates_with_cached_minute_bars": broad_with_minute,
        "restricted_context_rows": int(len(context_df)),
        "signal_rows": int(len(signals)),
        "replay_rows": int(len(replays)),
        "leaderboard_rows": int(len(leaderboard)),
    }
    (out / "coverage.json").write_text(json.dumps(coverage, indent=2), encoding="utf-8")

    print("OFFLINE_CACHE_REPLAY_DONE", json.dumps(coverage))
    if not signals.empty:
        print("SIGNAL_COUNTS")
        print(signals.groupby(["strategy_id", "variant_id", "direction", "split"]).size().reset_index(name="n").to_string(index=False))
    if not leaderboard.empty:
        cols = [c for c in ["strategy_id", "variant_id", "direction", "rule_id", "validation_n", "validation_profit_factor", "validation_expectancy", "test_profit_factor", "robustness_score"] if c in leaderboard.columns]
        print("LEADERBOARD")
        print(leaderboard[cols].head(20).to_string(index=False))


if __name__ == "__main__":
    main()
