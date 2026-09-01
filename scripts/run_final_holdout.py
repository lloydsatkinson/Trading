from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.run_fixed_stop_replay import _bars_frame, _load_inputs, _market_close, select_frozen_candidates
from trading_lab.alpaca_intraday import Alpaca
from trading_lab.fixed_stop import simulate_fixed_stop


FINAL_CONFIGS = {
    "SSR_FLUSH_RECLAIM_FINAL": {
        "candidate": "SSR_FLUSH_RECLAIM_RISK_3_5",
        "stop_pct": 0.20,
        "hold_minutes": 90,
        "target_r": 3.0,
    },
    "FAILED_HOD_BREAK_FINAL": {
        "candidate": "FAILED_HOD_BREAK_30_50_MIDDAY",
        "stop_pct": 0.05,
        "hold_minutes": 10,
        "target_r": 2.0,
    },
    "POP_AND_DROP_FINAL": {
        "candidate": "POP_AND_DROP_EXTREME_75_PLUS",
        "stop_pct": 0.15,
        "hold_minutes": 60,
        "target_r": 3.0,
    },
}


def final_target(side: str, entry: float, original_stop: float, target_r: float) -> float:
    side = side.upper()
    if side not in {"LONG", "SHORT"}:
        raise ValueError("side must be LONG or SHORT")
    risk = entry - original_stop if side == "LONG" else original_stop - entry
    if risk <= 0 or target_r <= 0:
        raise ValueError("structural risk and target R must be positive")
    return float(entry + target_r * risk if side == "LONG" else entry - target_r * risk)


def _validate_final_input(root: Path) -> dict:
    manifest_path = root / "history" / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"missing {manifest_path}")
    manifest = json.loads(manifest_path.read_text())
    sessions = [str(v)[:10] for v in manifest.get("session_dates", [])]
    if len(sessions) != 12 or sessions[0] != "2026-08-12" or sessions[-1] != "2026-08-27":
        raise RuntimeError(f"final holdout must be exactly 2026-08-12..2026-08-27 (12 sessions), got {sessions}")
    return manifest


def _configured(candidates: pd.DataFrame) -> pd.DataFrame:
    chunks = []
    for name, cfg in FINAL_CONFIGS.items():
        g = candidates[candidates["candidate"].eq(cfg["candidate"])].copy()
        g["config"] = name
        g["fixed_stop_pct"] = float(cfg["stop_pct"])
        g["fixed_hold_minutes"] = int(cfg["hold_minutes"])
        g["fixed_target_r"] = float(cfg["target_r"])
        chunks.append(g)
    if not chunks:
        return pd.DataFrame()
    return pd.concat(chunks, ignore_index=True).sort_values(["session_date", "config", "ticker"]).reset_index(drop=True)


def _simulate(row, bars: pd.DataFrame, slip_bps: float) -> dict:
    target = final_target(str(row.side), float(row.entry), float(row.stop), float(row.fixed_target_r))
    r = simulate_fixed_stop(
        bars,
        side=str(row.side),
        entry=float(row.entry),
        target=target,
        stop_pct=float(row.fixed_stop_pct),
        slip_bps=slip_bps,
        hold_minutes=int(row.fixed_hold_minutes),
    )
    risk_pct = ((float(row.entry) - float(row.stop)) / float(row.entry)) if row.side == "LONG" else ((float(row.stop) - float(row.entry)) / float(row.entry))
    realized_r = float(r["return_pct"]) / risk_pct
    return {
        "config": row.config,
        "candidate": row.candidate,
        "strategy": row.strategy,
        "side": row.side,
        "ticker": row.ticker,
        "session_date": row.session_date,
        "entry_ts": row.entry_ts.isoformat(),
        "entry": float(row.entry),
        "original_stop": float(row.stop),
        "structural_risk_pct": float(risk_pct),
        "fixed_stop_pct": float(row.fixed_stop_pct),
        "hold_minutes": int(row.fixed_hold_minutes),
        "target_r": float(row.fixed_target_r),
        "target": float(target),
        "exit": float(r["exit"]),
        "exit_ts": r["exit_ts"],
        "reason": r["reason"],
        "return_pct": float(r["return_pct"]),
        "realized_r": float(realized_r),
        "pnl_on_1000": float(r["return_pct"] * 1000.0),
        "slip_bps": float(slip_bps),
    }


def replay_final(client: Alpaca, configured: pd.DataFrame, *, slip_levels: list[float]) -> tuple[pd.DataFrame, list[dict]]:
    out, missing = [], []
    for session_date, day in configured.groupby("session_date", sort=True):
        symbols = sorted(day["ticker"].unique().tolist())
        start = day["entry_ts"].min().to_pydatetime()
        end = _market_close(str(session_date), start.tzinfo)
        raw_day = client.bars(symbols, "1Min", start, end, str(session_date))
        for _, row in day.iterrows():
            b = _bars_frame(raw_day.get(str(row.ticker).upper(), []), pd.Timestamp(row.entry_ts))
            if b.empty:
                missing.append({"session_date": session_date, "ticker": row.ticker, "config": row.config, "reason": "NO_BARS"})
                continue
            for slip in slip_levels:
                out.append(_simulate(row, b, slip))
    return pd.DataFrame(out), missing


def _pf(v: pd.Series) -> float:
    pos = float(v[v > 0].sum())
    neg = float(-v[v < 0].sum())
    return pos / neg if neg > 0 else (float("inf") if pos > 0 else 0.0)


def _dd(v: pd.Series) -> float:
    eq = pd.Series([0.0] + v.cumsum().tolist())
    return float((eq.cummax() - eq).max())


def _metrics(df: pd.DataFrame, sessions: int) -> pd.DataFrame:
    rows = []
    for (config, slip), g in df.groupby(["config", "slip_bps"], sort=True):
        ret = pd.to_numeric(g["return_pct"], errors="coerce").dropna()
        rr = pd.to_numeric(g["realized_r"], errors="coerce").dropna()
        rows.append({
            "config": config,
            "side": g["side"].iloc[0],
            "slip_bps": float(slip),
            "n": int(len(g)),
            "trades_per_day": float(len(g) / sessions),
            "return_pf": _pf(ret),
            "r_profit_factor": _pf(rr),
            "expectancy_r": float(rr.mean()),
            "win_rate": float((ret > 0).mean()),
            "avg_return_pct": float(ret.mean()),
            "avg_pnl_on_1000": float(ret.mean() * 1000.0),
            "total_pnl_on_1000_each_trade": float(ret.sum() * 1000.0),
            "max_drawdown_r": _dd(rr),
            "max_drawdown_return_points": _dd(ret),
        })
    return pd.DataFrame(rows)


def _leaderboard(metrics: pd.DataFrame, normal_slip: float) -> pd.DataFrame:
    normal = metrics[np.isclose(metrics["slip_bps"], normal_slip)].copy()
    stress = metrics[np.isclose(metrics["slip_bps"], normal_slip * 2)].copy()
    stress = stress[["config", "return_pf", "r_profit_factor", "expectancy_r", "avg_return_pct"]].rename(columns={
        "return_pf": "return_pf_2x",
        "r_profit_factor": "r_profit_factor_2x",
        "expectancy_r": "expectancy_r_2x",
        "avg_return_pct": "avg_return_pct_2x",
    })
    board = normal.merge(stress, on="config", how="left")
    statuses = []
    for _, r in board.iterrows():
        if int(r.n) < 8:
            status = "INCONCLUSIVE_FINAL_SAMPLE"
        else:
            passed = (
                r.return_pf >= 1.30
                and r.r_profit_factor >= 1.30
                and r.expectancy_r > 0
                and r.return_pf_2x > 1.05
                and r.r_profit_factor_2x > 1.05
                and r.expectancy_r_2x > 0
            )
            if passed:
                status = "FINAL_HOLDOUT_PASS" if r.side == "LONG" else "FINAL_EDGE_CONFIRMED_BORROW_UNVERIFIED"
            else:
                status = "FINAL_HOLDOUT_FAIL"
        statuses.append(status)
    board["status"] = statuses
    return board.sort_values(["status", "r_profit_factor"], ascending=[True, False]).reset_index(drop=True)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--input", default="output/final_raw")
    p.add_argument("--output", default="output/final_holdout")
    p.add_argument("--feed", default="sip")
    p.add_argument("--slip-bps", type=float, default=20.0)
    a = p.parse_args()

    root = Path(a.input)
    outdir = Path(a.output)
    outdir.mkdir(parents=True, exist_ok=True)
    manifest = _validate_final_input(root)
    trades, coarse = _load_inputs(root)
    candidates = select_frozen_candidates(trades, coarse)
    configured = _configured(candidates)
    configured.to_csv(outdir / "frozen_candidates.csv", index=False)

    client = Alpaca(os.getenv("APCA_API_KEY_ID", ""), os.getenv("APCA_API_SECRET_KEY", ""), a.feed)
    replayed, missing = replay_final(client, configured, slip_levels=[a.slip_bps, a.slip_bps * 2])
    replayed.to_csv(outdir / "trades.csv", index=False)
    pd.DataFrame(missing).to_csv(outdir / "missing.csv", index=False)
    metrics = _metrics(replayed, 12)
    metrics.to_csv(outdir / "metrics.csv", index=False)
    board = _leaderboard(metrics, a.slip_bps)
    board.to_csv(outdir / "leaderboard.csv", index=False)

    final_manifest = {
        "raw_manifest": manifest,
        "final_configs": FINAL_CONFIGS,
        "candidate_rows": int(len(configured)),
        "normal_and_stress_expected_replays": int(len(configured) * 2),
        "replayed": int(len(replayed)),
        "missing": int(len(missing)),
        "normal_slip_bps": a.slip_bps,
        "stress_slip_bps": a.slip_bps * 2,
        "holdout_policy": "one-shot scoring of rules frozen before opening 2026-08-12 through 2026-08-27; no optimization performed on this block",
        "short_execution_caveat": "historical point-in-time borrow/locate availability and fees remain unverified",
    }
    (outdir / "manifest.json").write_text(json.dumps(final_manifest, indent=2))
    print(board.to_string(index=False))
    print(json.dumps(final_manifest, indent=2))


if __name__ == "__main__":
    main()
