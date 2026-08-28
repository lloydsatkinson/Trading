from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from scanner.serclick.pipeline import run_replay_from_cache
from scanner.serclick.reporting import (
    build_latest_results,
    build_shortlist,
    fixed_horizon_summary,
    summarize_replays,
    write_json,
)
from scanner.serclick.study import SerClickStudy


def read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path) if path.exists() and path.stat().st_size else pd.DataFrame()


def render_news(meta: dict, shortlist: pd.DataFrame, fixed: pd.DataFrame, replay_summary: pd.DataFrame) -> str:
    lines = [
        "# SerClick / Leo Research News",
        "",
        f"Run: `{meta['run_id']}` | {meta['start_date']} to {meta['end_date']} | {meta['sessions']} sessions | {meta['feed']}",
        "",
        f"Candidates: **{meta['candidates']}** | Ignitions: **{meta['ignitions']}** | Universe: **{meta['universe']}**",
        "",
    ]
    if not shortlist.empty:
        tradable = shortlist[shortlist["action"].eq("TRADABLE_RESEARCH_SIGNAL")]
        watch = shortlist[shortlist["action"].eq("WATCH")]
        lines.append(f"Latest-day priority signals: **{len(tradable)}** | BOTH watch names: **{len(watch)}**")
        if not tradable.empty:
            cols = [c for c in ["symbol", "population", "state", "ignition_window", "entry_price_slipped"] if c in tradable.columns]
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
            cols = ["variant", "split", "rule_id", "n", "expectancy", "win_rate", "profit_factor"]
            lines.extend(["", "## Best replay rules (development/validation only)", "", train[cols].to_markdown(index=False)])
    lines.extend(["", "> Research only. 09:30-10:30 remains an observation/trap-building window; priority execution research is LEO BOTH after 10:30 and after-hours."])
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

    fixed = fixed_horizon_summary(ignitions)
    fixed.to_csv(out_dir / "fixed_horizon_summary.csv", index=False)

    replay_rows = run_replay_from_cache(root=root, feed=args.feed, ignitions=ignitions)
    replay_rows.to_csv(out_dir / "replay_grid.csv", index=False)
    replay_summary = summarize_replays(replay_rows)
    replay_summary.to_csv(out_dir / "replay_summary.csv", index=False)

    shortlist = build_shortlist(candidates, transitions, ignitions)
    shortlist.to_csv(out_dir / "latest_shortlist.csv", index=False)

    latest = build_latest_results(meta, ignitions, replay_summary)
    write_json(out_dir / "latest_results.json", latest)
    (out_dir / "news.md").write_text(render_news(meta, shortlist, fixed, replay_summary), encoding="utf-8")

    latest_dir = root / "data" / "latest"
    latest_dir.mkdir(parents=True, exist_ok=True)
    write_json(latest_dir / "serclick_latest_results.json", latest)
    shortlist.to_csv(latest_dir / "serclick_latest_shortlist.csv", index=False)
    (latest_dir / "serclick_news.md").write_text(render_news(meta, shortlist, fixed, replay_summary), encoding="utf-8")

    print("REMOTE_PIPELINE_DONE", json.dumps({
        "run_id": meta["run_id"],
        "output_dir": str(out_dir),
        "replay_rows": len(replay_rows),
        "shortlist_rows": len(shortlist),
        "news": str(out_dir / "news.md"),
    }))


if __name__ == "__main__":
    main()
