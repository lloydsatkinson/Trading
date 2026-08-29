from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from scanner.serclick.marketcap import (
    enrich_market_caps,
    enrich_market_caps_from_history,
    load_or_fetch_market_cap_snapshot,
)
from scanner.serclick.pipeline import run_replay_from_cache
from scanner.serclick.reporting import (
    build_latest_results,
    build_shortlist,
    fixed_horizon_summary,
    select_best_hold_times,
    summarize_peak_timing,
    summarize_replays,
    summarize_replays_by_market_cap,
    write_json,
)
from scanner.serclick.study import SerClickStudy


def read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path) if path.exists() and path.stat().st_size else pd.DataFrame()


def render_news(
    meta: dict,
    shortlist: pd.DataFrame,
    fixed: pd.DataFrame,
    replay_summary: pd.DataFrame,
    market_cap_summary: pd.DataFrame,
    best_hold_times: pd.DataFrame | None = None,
    peak_timing: pd.DataFrame | None = None,
) -> str:
    best_hold_times = best_hold_times if best_hold_times is not None else pd.DataFrame()
    peak_timing = peak_timing if peak_timing is not None else pd.DataFrame()

    lines = [
        "# SerClick / Leo Research News",
        "",
        f"Run: `{meta['run_id']}` | {meta['start_date']} to {meta['end_date']} | {meta['sessions']} sessions | {meta['feed']}",
        "",
        f"Candidates: **{meta['candidates']}** | Ignitions: **{meta['ignitions']}** | Universe: **{meta['universe']}**",
        "",
        "Variable-stop replay: **3%, 5%, 7%, 10%, 15%, 20%, 30%, 40%, 50%** | economics shown for a **£1,000 position**.",
        "",
        "Hold-time replay: **5, 10, 15, 30, 45, 60, 90, 120, 180, 240 minutes** | same-session only, exiting before **20:00 ET**.",
        "",
    ]
    if not shortlist.empty:
        tradable = shortlist[shortlist["action"].eq("TRADABLE_RESEARCH_SIGNAL")]
        watch = shortlist[shortlist["action"].eq("WATCH")]
        lines.append(f"Latest-day priority signals: **{len(tradable)}** | BOTH watch names: **{len(watch)}**")
        if "market_cap_bucket" in shortlist.columns:
            counts = shortlist["market_cap_bucket"].fillna("UNKNOWN").value_counts()
            lines.append(
                "Market-cap tags: "
                f"**{int(counts.get('MICROCAP', 0))} microcap** | "
                f"{int(counts.get('SMALL_CAP', 0))} small-cap | "
                f"{int(counts.get('LARGER', 0))} larger | "
                f"{int(counts.get('UNKNOWN', 0))} unknown"
            )
        if not tradable.empty:
            cols = [c for c in [
                "symbol", "population", "state", "ignition_window", "entry_price_slipped",
                "market_cap_bucket", "market_cap",
            ] if c in tradable.columns]
            lines.extend(["", "## Latest research signals", "", tradable[cols].head(12).to_markdown(index=False)])
    if not fixed.empty:
        focus = fixed[
            fixed["variant"].isin(["LEO_BOTH_MIDDAY", "LEO_BOTH_AH", "MORNING_OBSERVATION"])
            & fixed["split"].isin(["validation", "test"])
        ].copy()
        if not focus.empty:
            cols = [c for c in ["variant", "split", "n", "mean_ret_60m", "median_ret_60m", "pf_ret_60m", "mean_ret_120m", "pf_ret_120m"] if c in focus.columns]
            lines.extend(["", "## Fixed-horizon check", "", focus[cols].to_markdown(index=False)])
    if not replay_summary.empty:
        train = replay_summary[
            replay_summary["variant"].isin(["LEO_BOTH_MIDDAY", "LEO_BOTH_AH"])
            & replay_summary["split"].isin(["development", "validation"])
            & (replay_summary["n"] >= 8)
        ].sort_values(["profit_factor", "expectancy"], ascending=[False, False]).head(8)
        if not train.empty:
            cols = [c for c in [
                "variant", "split", "rule_id", "stop_pct", "target_pct", "max_hold_minutes", "n",
                "expectancy", "win_rate", "profit_factor", "avg_pnl_gbp_1000",
                "planned_stop_gbp_1000", "worst_pnl_gbp_1000",
            ] if c in train.columns]
            lines.extend(["", "## Best variable-stop replay rules (development/validation only)", "", train[cols].to_markdown(index=False)])
    if not best_hold_times.empty:
        hold_focus = best_hold_times[
            best_hold_times["variant"].isin(["LEO_BOTH_MIDDAY", "LEO_BOTH_AH"])
        ].sort_values(["avg_pnl_gbp_1000", "profit_factor", "n"], ascending=[False, False, False]).head(12)
        if not hold_focus.empty:
            cols = [c for c in [
                "variant", "rule_id", "stop_pct", "target_pct", "max_hold_minutes", "n",
                "expectancy", "win_rate", "profit_factor", "avg_pnl_gbp_1000",
                "planned_stop_gbp_1000", "selection_splits",
            ] if c in hold_focus.columns]
            lines.extend(["", "## Max-profit hold times (development/validation only)", "", hold_focus[cols].to_markdown(index=False)])
    if not peak_timing.empty:
        peak_focus = peak_timing[
            peak_timing["variant"].isin(["LEO_BOTH_MIDDAY", "LEO_BOTH_AH"])
        ].copy()
        if not peak_focus.empty:
            sort_cols = [c for c in ["split", "variant", "market_cap_bucket"] if c in peak_focus.columns]
            if sort_cols:
                peak_focus = peak_focus.sort_values(sort_cols)
            cols = [c for c in [
                "market_cap_bucket", "variant", "split", "n_signals",
                "median_minutes_to_peak", "mean_minutes_to_peak", "median_peak_return_pct",
                "mean_peak_return_pct", "avg_peak_pnl_gbp_1000",
            ] if c in peak_focus.columns]
            lines.extend(["", "## Exact time-to-peak", "", peak_focus[cols].head(16).to_markdown(index=False)])
    if not market_cap_summary.empty:
        cap_focus = market_cap_summary[
            market_cap_summary["market_cap_bucket"].isin(["MICROCAP", "SMALL_CAP", "LARGER"])
            & market_cap_summary["variant"].isin(["LEO_BOTH_MIDDAY", "LEO_BOTH_AH"])
            & (market_cap_summary["n"] >= 8)
        ].sort_values(["profit_factor", "expectancy", "n"], ascending=[False, False, False]).head(8)
        if not cap_focus.empty:
            cols = [c for c in [
                "market_cap_bucket", "variant", "split", "rule_id", "stop_pct", "target_pct",
                "max_hold_minutes", "n", "expectancy", "win_rate", "profit_factor",
                "avg_pnl_gbp_1000", "planned_stop_gbp_1000", "worst_pnl_gbp_1000",
            ] if c in cap_focus.columns]
            lines.extend(["", "## Prospective market-cap / variable-stop check", "", cap_focus[cols].to_markdown(index=False)])
    lines.extend([
        "",
        "> Research only. Stop/target/hold selection uses development/validation only; forward results measure rather than optimize. Peak timing may be reported on forward signals but never used to retune them after observation. Market-cap tags are prospective from 2026-08-28 and are never backfilled onto the already-inspected historical sample. 09:30-10:30 remains an observation/trap-building window; priority execution research is LEO BOTH after 10:30 and after-hours.",
    ])
    return "\n".join(lines) + "\n"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--feed", default="sip", choices=["sip", "iex"])
    p.add_argument("--sessions", type=int, default=60)
    p.add_argument("--end-date", default=None)
    p.add_argument("--root", default=".")
    args = p.parse_args()

    root = Path(args.root)
    study = SerClickStudy(root=root, feed=args.feed, sessions=args.sessions, end_date=args.end_date)
    meta = study.run()
    out_dir = root / meta["output_dir"]

    candidates = read_csv(out_dir / "candidates.csv")
    transitions = read_csv(out_dir / "transitions.csv")
    ignitions = read_csv(out_dir / "ignitions_first.csv")

    signal_day = str(candidates["date"].astype(str).max()) if not candidates.empty else str(meta["end_date"])
    snapshot = load_or_fetch_market_cap_snapshot(root=root, signal_day=signal_day)
    snapshot.to_csv(out_dir / "market_cap_snapshot.csv.gz", index=False, compression="gzip")

    # Only date-matched snapshots previously captured by the forward process are
    # attached. Historical dates without a snapshot remain UNKNOWN.
    ignitions_tagged = enrich_market_caps_from_history(root=root, signals=ignitions)

    fixed = fixed_horizon_summary(ignitions)
    fixed.to_csv(out_dir / "fixed_horizon_summary.csv", index=False)

    replay_rows = run_replay_from_cache(root=root, feed=args.feed, ignitions=ignitions_tagged)
    replay_rows.to_csv(out_dir / "replay_grid.csv", index=False)
    replay_summary = summarize_replays(replay_rows)
    replay_summary.to_csv(out_dir / "replay_summary.csv", index=False)
    market_cap_summary = summarize_replays_by_market_cap(replay_rows)
    market_cap_summary.to_csv(out_dir / "market_cap_replay_summary.csv", index=False)
    best_hold_times = select_best_hold_times(replay_rows)
    best_hold_times.to_csv(out_dir / "best_hold_times.csv", index=False)
    peak_timing = summarize_peak_timing(replay_rows)
    peak_timing.to_csv(out_dir / "peak_timing_summary.csv", index=False)

    shortlist = build_shortlist(candidates, transitions, ignitions)
    shortlist = enrich_market_caps(shortlist, snapshot)
    shortlist.to_csv(out_dir / "latest_shortlist.csv", index=False)

    latest = build_latest_results(meta, ignitions_tagged, replay_summary)
    write_json(out_dir / "latest_results.json", latest)
    news = render_news(meta, shortlist, fixed, replay_summary, market_cap_summary, best_hold_times, peak_timing)
    (out_dir / "news.md").write_text(news, encoding="utf-8")

    latest_dir = root / "data" / "latest"
    latest_dir.mkdir(parents=True, exist_ok=True)
    write_json(latest_dir / "serclick_latest_results.json", latest)
    shortlist.to_csv(latest_dir / "serclick_latest_shortlist.csv", index=False)
    replay_summary.to_csv(latest_dir / "serclick_variable_stop_summary.csv", index=False)
    market_cap_summary.to_csv(latest_dir / "serclick_market_cap_summary.csv", index=False)
    best_hold_times.to_csv(latest_dir / "serclick_best_hold_times.csv", index=False)
    peak_timing.to_csv(latest_dir / "serclick_peak_timing_summary.csv", index=False)
    snapshot.to_csv(latest_dir / "serclick_market_cap_snapshot.csv.gz", index=False, compression="gzip")
    (latest_dir / "serclick_news.md").write_text(news, encoding="utf-8")

    tagged = int(shortlist["market_cap_bucket"].ne("UNKNOWN").sum()) if not shortlist.empty and "market_cap_bucket" in shortlist.columns else 0
    print("REMOTE_PIPELINE_DONE", json.dumps({
        "run_id": meta["run_id"],
        "output_dir": str(out_dir),
        "replay_rows": len(replay_rows),
        "shortlist_rows": len(shortlist),
        "best_hold_rows": len(best_hold_times),
        "peak_timing_rows": len(peak_timing),
        "market_cap_tagged": tagged,
        "news": str(out_dir / "news.md"),
    }))


if __name__ == "__main__":
    main()
