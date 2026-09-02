from __future__ import annotations

import argparse
import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from scanner.core.peak import analyze_same_session_peak
from scanner.core.replay import DEFAULT_SLIPPAGE_BPS, apply_entry_slippage, replay_signal_grid
from scanner.core.reporting import slippage_resilience, summarize_strategy_replays
from scanner.core.rules import default_rules_for_signal, rule_family_id
from scanner.multistrategy.study import MultiStrategyStudy
from scanner.portfolio.strategy_ranker import rank_strategies
from scanner.serclick.marketcap import enrich_market_caps_from_history
from scanner.serclick.study import SerClickStudy
from scanner.strategies.dan_irish.corporate_actions import mark_corporate_action_replays
from scanner.strategies.dan_irish.research import (
    add_retained_gain_bucket,
    build_dan_summaries,
    generate_dan_signal_set,
    make_cached_symbol_minute_loader,
    persist_dan_rule_identity,
    replay_dan_swing_signals,
    run_study_with_optional_dan,
    summarize_dan_threshold_grid,
)
from scanner.strategies.orb_stocks_in_play.strategy import generate_orb_signals
from scanner.strategies.serclick_leo.strategy import adapt_serclick_ignitions
from scanner.strategies.vwap_momentum.strategy import generate_vwap_signals

ET = ZoneInfo("America/New_York")
SERCLICK_BASELINE_END = date(2026, 8, 27)
TRADABLE_VARIANT_EXCLUSIONS = {"MORNING_OBSERVATION", "SERCLICK_CONTROL"}


@dataclass
class ResearchResult:
    output_dir: Path
    signals: pd.DataFrame
    replays: pd.DataFrame
    summary: pd.DataFrame
    market_cap_summary: pd.DataFrame
    leaderboard: pd.DataFrame
    slippage_summary: pd.DataFrame
    peak_timing: pd.DataFrame
    best_hold_times: pd.DataFrame
    skips: pd.DataFrame
    price_bucket_summary: pd.DataFrame
    retained_gain_summary: pd.DataFrame
    swing_hold_summary: pd.DataFrame
    overnight_gap_risk: pd.DataFrame
    censor_summary: pd.DataFrame
    dan_threshold_summary: pd.DataFrame


def read_csv(path: str | Path) -> pd.DataFrame:
    path = Path(path)
    return pd.read_csv(path) if path.exists() and path.stat().st_size else pd.DataFrame()


def reprice_signal_for_slippage(signal: dict, slippage_bps: float) -> dict:
    out = dict(signal)
    raw = float(out["entry_price_raw"])
    direction = str(out.get("direction", "LONG")).upper()
    out["entry_price_slipped"] = apply_entry_slippage(raw, direction, slippage_bps)
    out["slippage_bps"] = float(slippage_bps)
    return out


def session_end_for_strategy(strategy_id: str) -> str:
    return "20:00" if str(strategy_id).upper() == "SERCLICK_LEO" else "16:00"


def build_slippage_summary(summary: pd.DataFrame) -> pd.DataFrame:
    if summary.empty:
        return pd.DataFrame()
    required = {"strategy_id", "variant_id", "direction", "rule_id", "split", "slippage_bps", "profit_factor"}
    if not required.issubset(summary.columns):
        return pd.DataFrame()
    dims = ["strategy_id", "variant_id", "direction", "rule_id", "split"]
    if "setup_id" in summary.columns:
        dims.append("setup_id")
    rows = []
    for keys, group in summary.groupby(dims, dropna=False, sort=False):
        keys = keys if isinstance(keys, tuple) else (keys,)
        rows.append({**dict(zip(dims, keys)), **slippage_resilience(group)})
    return pd.DataFrame(rows)


def summarize_peak_timing(replays: pd.DataFrame, baseline_slippage_bps: float = 25.0) -> pd.DataFrame:
    required = {
        "strategy_id", "variant_id", "direction", "symbol", "date", "split",
        "slippage_bps", "peak_return_pct", "minutes_to_peak",
    }
    if replays.empty or not required.issubset(replays.columns):
        return pd.DataFrame()
    x = replays[pd.to_numeric(replays["slippage_bps"], errors="coerce").eq(float(baseline_slippage_bps))].copy()
    signal_key = ["strategy_id", "variant_id", "direction", "symbol", "date", "split"]
    if "setup_id" in x.columns:
        signal_key.append("setup_id")
    x = x.drop_duplicates(signal_key)
    dims = ["strategy_id", "variant_id", "direction", "split"]
    if "setup_id" in x.columns:
        dims.append("setup_id")
    if "market_cap_bucket" in x.columns:
        x["market_cap_bucket"] = x["market_cap_bucket"].fillna("UNKNOWN")
        dims.append("market_cap_bucket")
    rows = []
    for keys, group in x.groupby(dims, dropna=False, sort=False):
        peak = pd.to_numeric(group["peak_return_pct"], errors="coerce")
        mins = pd.to_numeric(group["minutes_to_peak"], errors="coerce")
        valid = peak.notna() & mins.notna()
        if not valid.any():
            continue
        keys = keys if isinstance(keys, tuple) else (keys,)
        row = dict(zip(dims, keys))
        row.update({
            "n_signals": int(valid.sum()),
            "mean_peak_return_pct": float(peak[valid].mean()),
            "median_peak_return_pct": float(peak[valid].median()),
            "avg_peak_pnl_gbp_1000": float(peak[valid].mean() * 1000.0),
            "mean_minutes_to_peak": float(mins[valid].mean()),
            "median_minutes_to_peak": float(mins[valid].median()),
        })
        rows.append(row)
    return pd.DataFrame(rows)


def _minute_cache(root: Path, namespace: str, day: str, feed: str) -> Path:
    return root / "data" / "cache" / namespace / "minute" / f"{day}_{feed.lower()}.csv.gz"


def _load_minute_bars(root: Path, namespace: str, day: str, feed: str) -> pd.DataFrame:
    path = _minute_cache(root, namespace, day, feed)
    if not path.exists():
        return pd.DataFrame()
    bars = pd.read_csv(path)
    if not bars.empty:
        bars["symbol"] = bars["symbol"].astype(str)
        if "timestamp" in bars.columns:
            bars["timestamp"] = pd.to_datetime(bars["timestamp"], utc=True, errors="coerce")
    return bars


def _load_symbol_minute_bars(root: Path, namespace: str, day: str, feed: str, symbol: str) -> pd.DataFrame:
    bars = _load_minute_bars(root, namespace, day, feed)
    if bars.empty or "symbol" not in bars.columns:
        return pd.DataFrame()
    return bars[bars["symbol"].eq(str(symbol))].copy()


def generate_price_volume_signals(
    root: str | Path,
    feed: str,
    contexts: pd.DataFrame,
    strategies: Iterable[str] = ("orb", "vwap"),
) -> tuple[pd.DataFrame, pd.DataFrame]:
    root = Path(root)
    selected = {str(s).lower() for s in strategies}
    generators = []
    if "orb" in selected:
        generators.append(("orb", generate_orb_signals))
    if "vwap" in selected:
        generators.append(("vwap", generate_vwap_signals))
    if contexts.empty or not generators:
        return pd.DataFrame(), pd.DataFrame()

    signals: list[pd.DataFrame] = []
    skips: list[dict] = []
    for day, day_contexts in contexts.groupby(contexts["date"].astype(str), sort=True):
        bars = _load_minute_bars(root, "multistrategy_alpaca", str(day), feed)
        if bars.empty:
            for row in day_contexts.to_dict("records"):
                skips.append({"symbol": row.get("symbol"), "date": str(day), "reason": "MISSING_MINUTE_CACHE"})
            continue
        for context in day_contexts.to_dict("records"):
            symbol = str(context.get("symbol"))
            symbol_bars = bars[bars["symbol"].eq(symbol)].copy()
            if symbol_bars.empty:
                skips.append({"symbol": symbol, "date": str(day), "reason": "NO_SYMBOL_MINUTE_BARS"})
                continue
            emitted = False
            for strategy_key, generator in generators:
                out = generator(symbol_bars, context)
                if out.empty:
                    continue
                out = out.copy()
                out["_cache_namespace"] = "multistrategy_alpaca"
                signals.append(out)
                emitted = True
            if not emitted:
                skips.append({"symbol": symbol, "date": str(day), "reason": "NO_STRATEGY_SIGNAL"})
    return (
        pd.concat(signals, ignore_index=True) if signals else pd.DataFrame(),
        pd.DataFrame(skips),
    )


def _serclick_signal_sets(
    root: Path,
    feed: str,
    requested_end_date: str | None,
) -> tuple[pd.DataFrame, list[dict]]:
    """Return the frozen historical SerClick block plus prospective-forward rows."""
    metas: list[dict] = []
    frames: list[pd.DataFrame] = []

    baseline = SerClickStudy(root=root, feed=feed, sessions=60, end_date=str(SERCLICK_BASELINE_END))
    baseline_meta = baseline.run()
    metas.append(baseline_meta)
    baseline_dir = root / baseline_meta["output_dir"]
    baseline_ignitions = read_csv(baseline_dir / "ignitions_first.csv")
    if not baseline_ignitions.empty:
        baseline_ignitions = enrich_market_caps_from_history(root, baseline_ignitions)
        base_signals = adapt_serclick_ignitions(baseline_ignitions)
        base_signals["_cache_namespace"] = "serclick_alpaca"
        frames.append(base_signals)

    end = pd.Timestamp(requested_end_date).date() if requested_end_date else datetime.now(ET).date()
    if end <= SERCLICK_BASELINE_END:
        return (pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(), metas)

    probe = SerClickStudy(root=root, feed=feed, sessions=1, end_date=str(end))
    calendar = probe.api.calendar(str(SERCLICK_BASELINE_END + pd.Timedelta(days=1)), str(end))
    forward_sessions = len(calendar)
    if forward_sessions <= 0:
        return (pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(), metas)

    forward = SerClickStudy(root=root, feed=feed, sessions=forward_sessions, end_date=str(end))
    forward_meta = forward.run()
    metas.append(forward_meta)
    forward_dir = root / forward_meta["output_dir"]
    forward_ignitions = read_csv(forward_dir / "ignitions_first.csv")
    if not forward_ignitions.empty:
        forward_ignitions["split"] = "forward"
        forward_ignitions = enrich_market_caps_from_history(root, forward_ignitions)
        forward_signals = adapt_serclick_ignitions(forward_ignitions)
        forward_signals["split"] = "forward"
        forward_signals["_cache_namespace"] = "serclick_alpaca"
        frames.append(forward_signals)
    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if not combined.empty:
        combined = combined.drop_duplicates(["strategy_id", "variant_id", "symbol", "date", "entry_timestamp"], keep="first")
    return combined, metas


def replay_signals(
    root: str | Path,
    feed: str,
    signals: pd.DataFrame,
    slippage_bps: Iterable[float] = DEFAULT_SLIPPAGE_BPS,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if signals.empty:
        return pd.DataFrame(), pd.DataFrame()
    root = Path(root)
    frames: list[pd.DataFrame] = []
    skips: list[dict] = []
    for (namespace, day), group in signals.groupby([signals["_cache_namespace"], signals["date"].astype(str)], sort=True):
        bars = _load_minute_bars(root, str(namespace), str(day), feed)
        if bars.empty:
            skips.append({"date": str(day), "reason": "MISSING_REPLAY_CACHE", "cache_namespace": namespace})
            continue
        for signal in group.to_dict("records"):
            symbol_bars = bars[bars["symbol"].eq(str(signal["symbol"]))].copy()
            if symbol_bars.empty:
                skips.append({"symbol": signal.get("symbol"), "date": str(day), "reason": "MISSING_REPLAY_SYMBOL", "cache_namespace": namespace})
                continue
            is_serclick = str(signal.get("strategy_id")) == "SERCLICK_LEO"
            session_end = session_end_for_strategy(str(signal.get("strategy_id")))
            for bps in slippage_bps:
                priced = reprice_signal_for_slippage(signal, float(bps))
                peak = analyze_same_session_peak(
                    symbol_bars,
                    float(priced["entry_price_slipped"]),
                    priced["entry_timestamp"],
                    str(priced.get("direction", "LONG")),
                    session_end=session_end,
                )
                rules = default_rules_for_signal(priced, serclick=is_serclick)
                replay = replay_signal_grid(symbol_bars, priced, rules, session_end=session_end)
                if replay.empty:
                    continue
                replay["rule_id"] = [rule_family_id(rule) for rule in rules]
                replay["slippage_bps"] = float(bps)
                for key, value in peak.to_dict().items():
                    replay[key] = value
                frames.append(replay)
    return (
        pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(),
        pd.DataFrame(skips),
    )


def _best_holds(leaderboard: pd.DataFrame) -> pd.DataFrame:
    if leaderboard.empty:
        return pd.DataFrame()
    out = leaderboard.sort_values(
        ["robustness_score", "validation_profit_factor", "validation_expectancy"],
        ascending=[False, False, False],
    )
    group_cols = ["strategy_id", "variant_id", "direction"]
    return out.groupby(group_cols, sort=False, as_index=False).head(1).reset_index(drop=True)


def render_news(meta: dict, signals: pd.DataFrame, leaderboard: pd.DataFrame, peak_timing: pd.DataFrame) -> str:
    lines = [
        "# Multi-Strategy Microcap / Small-Cap Research",
        "",
        f"Run: `{meta['run_id']}` | {meta.get('start_date')} to {meta.get('end_date')} | feed {meta.get('feed')}",
        "",
        "Strategies: ORB Stocks-in-Play, High-RVOL VWAP Momentum/Reclaim, SerClick/Leo, Dan Irish Secondary Expansion, and Dan-inspired swing continuation.",
        "",
        "Execution stress: **10, 25, 50, 75, 100 bps** adverse entry slippage; next-bar entries only.",
        "",
        "Intraday holds: **5, 10, 15, 30, 45, 60, 90, 120, 180, 240 minutes + EOD**. Dan swing holds: **1, 2, 3, 4, 5, 7, 10 sessions**, with gap-through stops and incomplete-horizon censoring.",
        "",
    ]
    if not signals.empty:
        counts = signals.groupby(["strategy_id", "variant_id"]).size().reset_index(name="signals")
        lines.extend(["## Signals", "", counts.to_markdown(index=False), ""])
    if not leaderboard.empty:
        cols = [c for c in [
            "strategy_id", "variant_id", "setup_id", "direction", "rule_id", "max_hold_minutes", "max_hold_sessions", "validation_n",
            "validation_profit_factor", "validation_expectancy", "validation_median_return",
            "slippage_last_pf_ge_1_0_bps", "robustness_score", "test_profit_factor", "forward_profit_factor",
        ] if c in leaderboard.columns]
        lines.extend(["## Validation-led leaderboard", "", leaderboard[cols].head(15).to_markdown(index=False), ""])
    if not peak_timing.empty:
        cols = [c for c in [
            "strategy_id", "variant_id", "setup_id", "direction", "split", "market_cap_bucket", "n_signals",
            "median_peak_return_pct", "median_minutes_to_peak",
        ] if c in peak_timing.columns]
        lines.extend(["## Exact intraday peak timing", "", peak_timing[cols].head(15).to_markdown(index=False), ""])
    lines.extend([
        "> Research only. Development/validation may select rules; locked test and forward observations never tune the selection score. Dan swing variants are Dan-inspired hypotheses unless directly evidenced otherwise. Historical market-cap values that were not captured contemporaneously remain UNKNOWN rather than being backfilled from future data.",
        "",
    ])
    return "\n".join(lines)


def _component_meta(meta: dict) -> dict:
    excluded = {"candidate_contexts", "dan_candidate_contexts", "daily_bars"}
    return {k: v for k, v in meta.items() if k not in excluded}


def run_research(
    root: str | Path = ".",
    feed: str = "sip",
    sessions: int = 60,
    end_date: str | None = None,
    strategies: Iterable[str] = ("orb", "vwap", "serclick", "dan"),
    min_n: int = 20,
) -> ResearchResult:
    root = Path(root)
    selected = {str(s).lower() for s in strategies}
    run_id = f"multistrategy_{datetime.now(ET).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    output_dir = root / "data" / "research" / "multistrategy" / run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    signal_frames: list[pd.DataFrame] = []
    skip_frames: list[pd.DataFrame] = []
    meta_parts: list[dict] = []
    study_meta: dict | None = None
    study: MultiStrategyStudy | None = None

    needs_price_volume = bool(selected & {"orb", "vwap"})
    needs_dan = "dan" in selected
    dan_minute_loader = (
        make_cached_symbol_minute_loader(_load_minute_bars, max_days=24)
        if needs_dan
        else _load_symbol_minute_bars
    )
    if needs_price_volume or needs_dan:
        study = MultiStrategyStudy(root=root, feed=feed, sessions=sessions, end_date=end_date)
        study_meta = run_study_with_optional_dan(
            study,
            needs_price_volume=needs_price_volume,
            needs_dan=needs_dan,
        )
        meta_parts.append(_component_meta(study_meta))

        if needs_price_volume:
            pv_signals, pv_skips = generate_price_volume_signals(
                root,
                feed,
                study_meta.get("candidate_contexts", pd.DataFrame()),
                strategies=tuple(selected & {"orb", "vwap"}),
            )
            if not pv_signals.empty:
                signal_frames.append(pv_signals)
            if not pv_skips.empty:
                skip_frames.append(pv_skips)

        if needs_dan:
            dan_signals, dan_skips = generate_dan_signal_set(
                root,
                feed,
                study,
                study_meta,
                dan_minute_loader,
            )
            if not dan_signals.empty:
                signal_frames.append(dan_signals)
            if not dan_skips.empty:
                skip_frames.append(dan_skips)

    if "serclick" in selected:
        serclick_signals, serclick_metas = _serclick_signal_sets(root, feed, end_date)
        meta_parts.extend(serclick_metas)
        if not serclick_signals.empty:
            signal_frames.append(serclick_signals)

    signals = pd.concat(signal_frames, ignore_index=True, sort=False) if signal_frames else pd.DataFrame()
    if not signals.empty:
        dedup_cols = ["strategy_id", "variant_id", "symbol", "date", "entry_timestamp"]
        if "setup_id" in signals.columns:
            dedup_cols.append("setup_id")
        signals = signals.drop_duplicates(dedup_cols, keep="first")

    replay_frames: list[pd.DataFrame] = []
    swing_replays = pd.DataFrame()
    if not signals.empty:
        if "_replay_mode" in signals.columns:
            replay_mode = signals["_replay_mode"].fillna("intraday").astype(str)
        else:
            replay_mode = pd.Series("intraday", index=signals.index)
        intraday_signals = signals[replay_mode.eq("intraday")].copy()
        swing_signals = signals[replay_mode.eq("swing")].copy()

        intraday_replays, replay_skips = replay_signals(root, feed, intraday_signals)
        if not intraday_replays.empty:
            replay_frames.append(intraday_replays)
        if not replay_skips.empty:
            skip_frames.append(replay_skips)

        if not swing_signals.empty and study_meta is not None:
            swing_replays, swing_skips = replay_dan_swing_signals(
                root,
                feed,
                swing_signals,
                study_meta.get("daily_bars", pd.DataFrame()),
                study_meta.get("split_end_dates", {}),
                dan_minute_loader,
            )
            if not swing_replays.empty:
                audit_status = str(study_meta.get("corporate_action_audit_status") or "UNAVAILABLE").upper()
                if audit_status == "OK":
                    swing_replays = mark_corporate_action_replays(
                        swing_replays,
                        study_meta.get("corporate_actions", pd.DataFrame()),
                    )
                    swing_replays["corporate_action_audit_unavailable"] = False
                else:
                    swing_replays = swing_replays.copy()
                    swing_replays["corporate_action_flag"] = False
                    swing_replays["corporate_action_type"] = None
                    swing_replays["corporate_action_date"] = None
                    swing_replays["corporate_action_audit_unavailable"] = True
                    swing_replays["selection_eligible_replay"] = False
                replay_frames.append(swing_replays)
            if not swing_skips.empty:
                skip_frames.append(swing_skips)

    replays = pd.concat(replay_frames, ignore_index=True, sort=False) if replay_frames else pd.DataFrame()
    replays = add_retained_gain_bucket(replays)
    if not replays.empty and "strategy_id" in replays.columns:
        dan_mask = replays["strategy_id"].astype(str).eq("DAN_IRISH")
        if dan_mask.any():
            dan_identified = persist_dan_rule_identity(replays.loc[dan_mask].copy())
            replays = pd.concat([replays.loc[~dan_mask].copy(), dan_identified], ignore_index=True, sort=False)
    skips = pd.concat(skip_frames, ignore_index=True, sort=False) if skip_frames else pd.DataFrame()

    summary = summarize_strategy_replays(replays)
    market_cap_summary = summarize_strategy_replays(replays, segment_cols=("market_cap_bucket",)) if not replays.empty else pd.DataFrame()
    slippage_summary = build_slippage_summary(summary)
    peak_timing = summarize_peak_timing(replays)

    dan_replays = (
        replays[replays["strategy_id"].astype(str).eq("DAN_IRISH")].copy()
        if not replays.empty and "strategy_id" in replays.columns
        else pd.DataFrame()
    )
    dan_summaries = build_dan_summaries(dan_replays, swing_replays)
    price_bucket_summary = dan_summaries["price_bucket_summary"]
    retained_gain_summary = dan_summaries["retained_gain_summary"]
    swing_hold_summary = dan_summaries["swing_hold_summary"]
    overnight_gap_risk = dan_summaries["overnight_gap_risk"]
    censor_summary = dan_summaries["censor_summary"]
    dan_threshold_summary = summarize_dan_threshold_grid(dan_replays)

    ranking_source = summary.copy()
    if not ranking_source.empty and "variant_id" in ranking_source.columns:
        ranking_source = ranking_source[~ranking_source["variant_id"].isin(TRADABLE_VARIANT_EXCLUSIONS)]
    leaderboard = rank_strategies(ranking_source, min_n=min_n, baseline_slippage_bps=25.0) if not ranking_source.empty else pd.DataFrame()
    best_hold_times = _best_holds(leaderboard)

    start_dates = [m.get("start_date") for m in meta_parts if m.get("start_date")]
    end_dates = [m.get("end_date") for m in meta_parts if m.get("end_date")]
    meta = {
        "run_id": run_id,
        "feed": feed.upper(),
        "market_data_adjustment": (
            str(study_meta.get("bar_adjustment") or "raw") if study_meta is not None else "raw"
        ),
        "corporate_action_audit_status": (
            str(study_meta.get("corporate_action_audit_status") or "NOT_RUN") if study_meta is not None else "NOT_RUN"
        ),
        "requested_sessions": int(sessions),
        "strategies": sorted(selected),
        "start_date": min(start_dates) if start_dates else None,
        "end_date": max(end_dates) if end_dates else end_date,
        "signal_rows": int(len(signals)),
        "replay_rows": int(len(replays)),
        "selection": "VALIDATION_25BPS_ONLY",
        "production_min_expectancy": 0.05,
        "serclick_historical_lock_end": str(SERCLICK_BASELINE_END),
        "serclick_forward_start": "2026-08-28",
        "dan_swing_attribution": "DAN_INSPIRED",
        "components": meta_parts,
    }

    signals.to_csv(output_dir / "signals.csv", index=False)
    replays.to_csv(output_dir / "replay_grid.csv.gz", index=False, compression="gzip")
    summary.to_csv(output_dir / "strategy_summary.csv", index=False)
    market_cap_summary.to_csv(output_dir / "market_cap_summary.csv", index=False)
    leaderboard.to_csv(output_dir / "leaderboard.csv", index=False)
    slippage_summary.to_csv(output_dir / "slippage_summary.csv", index=False)
    peak_timing.to_csv(output_dir / "peak_timing.csv", index=False)
    best_hold_times.to_csv(output_dir / "best_hold_times.csv", index=False)
    price_bucket_summary.to_csv(output_dir / "price_bucket_summary.csv", index=False)
    retained_gain_summary.to_csv(output_dir / "retained_gain_summary.csv", index=False)
    swing_hold_summary.to_csv(output_dir / "swing_hold_summary.csv", index=False)
    overnight_gap_risk.to_csv(output_dir / "overnight_gap_risk.csv", index=False)
    censor_summary.to_csv(output_dir / "censor_summary.csv", index=False)
    dan_threshold_summary.to_csv(output_dir / "dan_threshold_summary.csv", index=False)
    skips.to_csv(output_dir / "skips.csv", index=False)
    (output_dir / "run_meta.json").write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")
    news = render_news(meta, signals, leaderboard, peak_timing)
    (output_dir / "news.md").write_text(news, encoding="utf-8")

    latest = root / "data" / "latest"
    latest.mkdir(parents=True, exist_ok=True)
    leaderboard.to_csv(latest / "multistrategy_leaderboard.csv", index=False)
    best_hold_times.to_csv(latest / "multistrategy_best_hold_times.csv", index=False)
    peak_timing.to_csv(latest / "multistrategy_peak_timing.csv", index=False)
    signals.to_csv(latest / "multistrategy_signals.csv", index=False)
    price_bucket_summary.to_csv(latest / "dan_price_bucket_summary.csv", index=False)
    retained_gain_summary.to_csv(latest / "dan_retained_gain_summary.csv", index=False)
    swing_hold_summary.to_csv(latest / "dan_swing_hold_summary.csv", index=False)
    overnight_gap_risk.to_csv(latest / "dan_overnight_gap_risk.csv", index=False)
    censor_summary.to_csv(latest / "dan_censor_summary.csv", index=False)
    dan_threshold_summary.to_csv(latest / "dan_threshold_summary.csv", index=False)
    (latest / "multistrategy_news.md").write_text(news, encoding="utf-8")
    (latest / "multistrategy_run_meta.json").write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")

    return ResearchResult(
        output_dir=output_dir,
        signals=signals,
        replays=replays,
        summary=summary,
        market_cap_summary=market_cap_summary,
        leaderboard=leaderboard,
        slippage_summary=slippage_summary,
        peak_timing=peak_timing,
        best_hold_times=best_hold_times,
        skips=skips,
        price_bucket_summary=price_bucket_summary,
        retained_gain_summary=retained_gain_summary,
        swing_hold_summary=swing_hold_summary,
        overnight_gap_risk=overnight_gap_risk,
        censor_summary=censor_summary,
        dan_threshold_summary=dan_threshold_summary,
    )


def _parse_strategies(value: str) -> tuple[str, ...]:
    if value.lower() == "all":
        return ("orb", "vwap", "serclick", "dan")
    parts = tuple(part.strip().lower() for part in value.split(",") if part.strip())
    invalid = set(parts) - {"orb", "vwap", "serclick", "dan"}
    if invalid:
        raise ValueError(f"Unknown strategies: {sorted(invalid)}")
    return parts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategy", default="all", help="all or comma-separated orb,vwap,serclick,dan")
    parser.add_argument("--feed", default="sip", choices=["sip", "iex"])
    parser.add_argument("--sessions", type=int, default=60)
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--root", default=".")
    parser.add_argument("--min-n", type=int, default=20)
    args = parser.parse_args()
    result = run_research(
        root=args.root,
        feed=args.feed,
        sessions=args.sessions,
        end_date=args.end_date,
        strategies=_parse_strategies(args.strategy),
        min_n=args.min_n,
    )
    print("MULTISTRATEGY_DONE", json.dumps({
        "output_dir": str(result.output_dir),
        "signals": len(result.signals),
        "replays": len(result.replays),
        "leaderboard_rows": len(result.leaderboard),
    }))


if __name__ == "__main__":
    main()