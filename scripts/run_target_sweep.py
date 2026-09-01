from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import pandas as pd

from scripts.run_fixed_stop_replay import (
    _bars_frame,
    _load_inputs,
    _market_close,
    _metric_rows,
    select_frozen_candidates,
)
from trading_lab.alpaca_intraday import Alpaca
from trading_lab.fixed_stop import simulate_fixed_stop


CONFIGS = {
    "SSR_RECLAIM_BALANCED": {
        "candidate": "SSR_FLUSH_RECLAIM_RISK_3_5",
        "stop_pct": 0.20,
        "hold_minutes": 90,
    },
    "FAILED_HOD_RISK_EFFICIENT": {
        "candidate": "FAILED_HOD_BREAK_30_50_MIDDAY",
        "stop_pct": 0.05,
        "hold_minutes": 10,
    },
    "FAILED_HOD_AGGRESSIVE": {
        "candidate": "FAILED_HOD_BREAK_30_50_MIDDAY",
        "stop_pct": 0.50,
        "hold_minutes": 30,
    },
    "POP_DROP_BALANCED": {
        "candidate": "POP_AND_DROP_EXTREME_75_PLUS",
        "stop_pct": 0.15,
        "hold_minutes": 60,
    },
}


def target_from_structural_risk(*, side: str, entry: float, original_stop: float, target_r: float) -> float:
    side = side.upper()
    if side not in {"LONG", "SHORT"}:
        raise ValueError("side must be LONG or SHORT")
    if target_r <= 0:
        raise ValueError("target_r must be positive")
    risk = entry - original_stop if side == "LONG" else original_stop - entry
    if risk <= 0:
        raise ValueError("original structural stop must define positive risk")
    return float(entry + target_r * risk if side == "LONG" else entry - target_r * risk)


def _configured_candidates(candidates: pd.DataFrame) -> pd.DataFrame:
    chunks = []
    for config_name, cfg in CONFIGS.items():
        g = candidates[candidates["candidate"].eq(cfg["candidate"])].copy()
        g["config"] = config_name
        g["fixed_stop_pct"] = float(cfg["stop_pct"])
        g["fixed_hold_minutes"] = int(cfg["hold_minutes"])
        chunks.append(g)
    return pd.concat(chunks, ignore_index=True).sort_values(["session_date", "config", "ticker"]).reset_index(drop=True)


def _target_metric_rows(df: pd.DataFrame, sessions: int) -> list[dict]:
    rows = []
    for (config_name, target_r), g in df.groupby(["config", "target_r"]):
        z = g.copy()
        z["candidate"] = config_name
        metric = _metric_rows(z, sessions, f"TARGET_{target_r:g}R")[0]
        metric["config"] = config_name
        metric["target_r"] = float(target_r)
        metric["stop_pct"] = float(g["stop_pct"].iloc[0])
        metric["hold_minutes"] = int(g["hold_minutes"].iloc[0])
        rows.append(metric)
    return rows


def replay_target_sweep(
    client: Alpaca,
    configured: pd.DataFrame,
    *,
    target_rs: list[float],
    slip_bps: float,
) -> tuple[pd.DataFrame, list[dict]]:
    out, missing = [], []
    max_hold = max(int(v["hold_minutes"]) for v in CONFIGS.values())
    for session_date, day in configured.groupby("session_date", sort=True):
        symbols = sorted(day["ticker"].unique().tolist())
        start = day["entry_ts"].min().to_pydatetime()
        end = _market_close(str(session_date), start.tzinfo)
        bars = client.bars(symbols, "1Min", start, end, str(session_date))
        for _, row in day.iterrows():
            b = _bars_frame(bars.get(str(row.ticker).upper(), []), pd.Timestamp(row.entry_ts))
            if b.empty:
                missing.append({"session_date": session_date, "ticker": row.ticker, "config": row.config, "reason": "NO_BARS"})
                continue
            for target_r in target_rs:
                target = target_from_structural_risk(
                    side=str(row.side),
                    entry=float(row.entry),
                    original_stop=float(row.stop),
                    target_r=float(target_r),
                )
                r = simulate_fixed_stop(
                    b,
                    side=str(row.side),
                    entry=float(row.entry),
                    target=target,
                    stop_pct=float(row.fixed_stop_pct),
                    slip_bps=slip_bps,
                    hold_minutes=int(row.fixed_hold_minutes),
                )
                out.append({
                    "config": row.config,
                    "candidate": row.candidate,
                    "strategy": row.strategy,
                    "side": row.side,
                    "ticker": row.ticker,
                    "session_date": row.session_date,
                    "split": row.split,
                    "entry_ts": row.entry_ts.isoformat(),
                    "entry": float(row.entry),
                    "original_stop": float(row.stop),
                    "stop_pct": float(row.fixed_stop_pct),
                    "hold_minutes": int(row.fixed_hold_minutes),
                    "target_r": float(target_r),
                    "target": float(target),
                    "exit": float(r["exit"]),
                    "exit_ts": r["exit_ts"],
                    "reason": r["reason"],
                    "return_pct": float(r["return_pct"]),
                    "pnl_on_1000": float(r["return_pct"] * 1000.0),
                })
    return pd.DataFrame(out), missing


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--input", default="input/intraday")
    p.add_argument("--output", default="output/target_sweep")
    p.add_argument("--target-sweep", default="0.5,1,1.5,2,2.5,3,4,5")
    p.add_argument("--slip-bps", type=float, default=20.0)
    p.add_argument("--feed", default="sip")
    a = p.parse_args()

    target_rs = sorted({float(v.strip()) for v in a.target_sweep.split(",") if v.strip()})
    if not target_rs or any(v <= 0 for v in target_rs):
        raise ValueError("target sweep must contain positive R multiples")

    outdir = Path(a.output)
    outdir.mkdir(parents=True, exist_ok=True)
    trades, coarse = _load_inputs(Path(a.input))
    candidates = select_frozen_candidates(trades, coarse)
    configured = _configured_candidates(candidates)
    client = Alpaca(os.getenv("APCA_API_KEY_ID", ""), os.getenv("APCA_API_SECRET_KEY", ""), a.feed)

    replayed, missing = replay_target_sweep(client, configured, target_rs=target_rs, slip_bps=a.slip_bps)
    replayed.to_csv(outdir / "target_sweep_trades.csv", index=False)
    pd.DataFrame(missing).to_csv(outdir / "missing.csv", index=False)

    rows = _target_metric_rows(replayed, 60)
    metrics = pd.DataFrame(rows)
    metrics.to_csv(outdir / "metrics.csv", index=False)

    split_rows = []
    for split, g in replayed.groupby("split"):
        for r in _target_metric_rows(g, max(1, g["session_date"].nunique())):
            r["split"] = split
            split_rows.append(r)
    splits = pd.DataFrame(split_rows)
    splits.to_csv(outdir / "metrics_splits.csv", index=False)

    dev = splits[splits["split"].eq("development")].copy()
    selected = (
        dev.sort_values(["config", "total_pnl_on_1000_each_trade", "profit_factor"], ascending=[True, False, False])
        .groupby("config", as_index=False)
        .head(1)[["config", "target_r"]]
        .rename(columns={"target_r": "selected_target_r_from_development"})
    )
    selected_report = splits.merge(selected, on="config", how="inner")
    selected_report = selected_report[
        selected_report["target_r"].eq(selected_report["selected_target_r_from_development"])
    ].copy()
    selected_report.to_csv(outdir / "selected_target_validation.csv", index=False)

    expected = len(configured) * len(target_rs)
    manifest = {
        "target_r": target_rs,
        "configs": CONFIGS,
        "configured_trade_rows": int(len(configured)),
        "expected_replays": int(expected),
        "replayed": int(len(replayed)),
        "coverage": float(len(replayed) / expected if expected else 0.0),
        "missing": int(len(missing)),
        "target_basis": "multiple of original chart-structural risk, independent of fixed emergency stop",
        "selection_rule": "max total $ P&L in development only; validation and holdout reporting-only",
        "final_august_2026_08_12_to_2026_08_27": "untouched",
    }
    (outdir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(metrics.to_string(index=False))
    print("\nSELECTED FROM DEVELOPMENT ONLY\n", selected_report.to_string(index=False))
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
