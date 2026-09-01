from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from trading_lab.alpaca_intraday import Alpaca
from trading_lab.fixed_stop import simulate_fixed_stop

NY = ZoneInfo("America/New_York")


def _load_inputs(root: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    trades_path = root / "trades.csv"
    coarse_path = root / "history" / "coarse_candidates.csv"
    if not trades_path.exists() or not coarse_path.exists():
        raise FileNotFoundError(f"expected {trades_path} and {coarse_path}")
    return pd.read_csv(trades_path), pd.read_csv(coarse_path)


def select_frozen_candidates(trades: pd.DataFrame, coarse: pd.DataFrame) -> pd.DataFrame:
    x = trades.merge(
        coarse[["date", "ticker", "previous_close"]],
        left_on=["session_date", "ticker"],
        right_on=["date", "ticker"],
        how="left",
        validate="many_to_one",
    )
    x["risk_pct"] = np.where(
        x["side"].eq("LONG"),
        (x["entry"] - x["stop"]) / x["entry"],
        (x["stop"] - x["entry"]) / x["entry"],
    )
    x["entry_vs_prev"] = x["entry"] / x["previous_close"] - 1.0
    et = pd.to_datetime(x["signal_ts"], utc=True).dt.tz_convert("America/New_York")
    x["signal_min"] = et.dt.hour * 60 + et.dt.minute

    ssr = x[
        x["strategy"].eq("SSR_FLUSH_RECLAIM")
        & x["risk_pct"].ge(0.03)
        & x["risk_pct"].lt(0.05)
    ].copy()
    ssr["candidate"] = "SSR_FLUSH_RECLAIM_RISK_3_5"

    fh = x[
        x["strategy"].eq("FAILED_HOD_BREAK")
        & x["signal_min"].ge(630)
        & x["signal_min"].le(780)
        & x["entry_vs_prev"].ge(0.30)
        & x["entry_vs_prev"].lt(0.50)
        & x["risk_pct"].lt(0.10)
    ].copy()
    fh["candidate"] = "FAILED_HOD_BREAK_30_50_MIDDAY"

    pop = x[
        x["strategy"].eq("POP_AND_DROP")
        & x["entry_vs_prev"].ge(0.75)
    ].copy()
    pop["candidate"] = "POP_AND_DROP_EXTREME_75_PLUS"

    out = pd.concat([ssr, fh, pop], ignore_index=True)
    out["entry_ts"] = pd.to_datetime(out["entry_ts"], utc=True)
    return out.sort_values(["session_date", "candidate", "ticker"]).reset_index(drop=True)


def parameter_grid(stops: list[float], holds: list[int]) -> list[tuple[float, int]]:
    clean_stops = sorted({float(v) for v in stops})
    clean_holds = sorted({int(v) for v in holds})
    return [(stop, hold) for stop in clean_stops for hold in clean_holds]


def _metric_rows(df: pd.DataFrame, sessions: int, label: str) -> list[dict]:
    rows = []
    for candidate, g in df.groupby("candidate"):
        v = pd.to_numeric(g["return_pct"], errors="coerce").dropna()
        pos = float(v[v > 0].sum())
        neg = float(-v[v < 0].sum())
        pf = pos / neg if neg > 0 else (float("inf") if pos > 0 else 0.0)
        eq = pd.Series([0.0] + v.cumsum().tolist())
        rows.append({
            "variant": label,
            "candidate": candidate,
            "n": int(len(v)),
            "trades_per_day": float(len(v) / max(1, sessions)),
            "profit_factor": float(pf),
            "avg_return_pct": float(v.mean()),
            "win_rate": float((v > 0).mean()),
            "max_drawdown_pct_points": float((eq.cummax() - eq).max()),
            "avg_pnl_on_1000": float(v.mean() * 1000.0),
            "total_pnl_on_1000_each_trade": float(v.sum() * 1000.0),
        })
    return rows


def _baseline(candidates: pd.DataFrame) -> pd.DataFrame:
    x = candidates.copy()
    x["return_pct"] = np.where(
        x["side"].eq("LONG"),
        (x["exit"] - x["entry"]) / x["entry"],
        (x["entry"] - x["exit"]) / x["entry"],
    )
    x["reason_fixed"] = x["reason"]
    return x


def _market_close(session_date: str, tzinfo) -> datetime:
    d = pd.Timestamp(session_date).date()
    return datetime(d.year, d.month, d.day, 16, 1, tzinfo=NY).astimezone(tzinfo)


def _bars_frame(raw: list[dict], entry_ts: pd.Timestamp) -> pd.DataFrame:
    b = pd.DataFrame(raw).rename(columns={"t":"timestamp","o":"open","h":"high","l":"low","c":"close","v":"volume"})
    if "timestamp" not in b.columns:
        return pd.DataFrame()
    b["timestamp"] = pd.to_datetime(b["timestamp"], utc=True)
    return b[b["timestamp"] >= entry_ts].copy()


def _trade_row(row, r: dict, stop_pct: float, hold_minutes: int) -> dict:
    return {
        "candidate": row.candidate,
        "strategy": row.strategy,
        "side": row.side,
        "ticker": row.ticker,
        "session_date": row.session_date,
        "split": row.split,
        "entry_ts": row.entry_ts.isoformat(),
        "entry": float(row.entry),
        "original_stop": float(row.stop),
        "fixed_stop": float(r["stop"]),
        "target": float(row.target),
        "exit": float(r["exit"]),
        "exit_ts": r["exit_ts"],
        "reason": r["reason"],
        "return_pct": float(r["return_pct"]),
        "pnl_on_1000": float(r["return_pct"] * 1000.0),
        "stop_pct": float(stop_pct),
        "hold_minutes": int(hold_minutes),
    }


def replay(
    client: Alpaca,
    candidates: pd.DataFrame,
    *,
    stop_pct: float,
    slip_bps: float,
    hold_minutes: int,
) -> tuple[pd.DataFrame, list[dict]]:
    return replay_parameter_sweep(
        client,
        candidates,
        stop_pcts=[stop_pct],
        slip_bps=slip_bps,
        holds=[hold_minutes],
    )


def replay_parameter_sweep(
    client: Alpaca,
    candidates: pd.DataFrame,
    *,
    stop_pcts: list[float],
    slip_bps: float,
    holds: list[int],
) -> tuple[pd.DataFrame, list[dict]]:
    out, missing = [], []
    grid = parameter_grid(stop_pcts, holds)
    for session_date, day in candidates.groupby("session_date", sort=True):
        symbols = sorted(day["ticker"].unique().tolist())
        start = day["entry_ts"].min().to_pydatetime()
        end = _market_close(str(session_date), start.tzinfo)
        bars = client.bars(symbols, "1Min", start, end, str(session_date))
        for _, row in day.iterrows():
            b = _bars_frame(bars.get(str(row.ticker).upper(), []), pd.Timestamp(row.entry_ts))
            if b.empty:
                missing.append({"session_date": session_date, "ticker": row.ticker, "candidate": row.candidate, "reason": "NO_BARS"})
                continue
            for stop_pct, hold in grid:
                r = simulate_fixed_stop(
                    b,
                    side=str(row.side),
                    entry=float(row.entry),
                    target=float(row.target),
                    stop_pct=stop_pct,
                    slip_bps=slip_bps,
                    hold_minutes=hold,
                )
                out.append(_trade_row(row, r, stop_pct, hold))
    return pd.DataFrame(out), missing


def _write_metrics(fixed: pd.DataFrame, outdir: Path, sessions: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows, split_rows = [], []
    for (stop_pct, hold), g in fixed.groupby(["stop_pct", "hold_minutes"], sort=True):
        label = f"FIXED_STOP_{stop_pct:.1%}_HOLD_{int(hold)}m"
        for r in _metric_rows(g, sessions, label):
            r["stop_pct"] = float(stop_pct)
            r["hold_minutes"] = int(hold)
            rows.append(r)
        for split, sg in g.groupby("split"):
            for r in _metric_rows(sg, max(1, sg["session_date"].nunique()), label):
                r["stop_pct"] = float(stop_pct)
                r["hold_minutes"] = int(hold)
                r["split"] = split
                split_rows.append(r)
    m = pd.DataFrame(rows)
    ms = pd.DataFrame(split_rows)
    m.to_csv(outdir / "metrics.csv", index=False)
    ms.to_csv(outdir / "metrics_splits.csv", index=False)
    return m, ms


def _parse_float_list(raw: str, fallback: float) -> list[float]:
    if not raw:
        return [float(fallback)]
    return sorted({float(v.strip()) for v in raw.split(",") if v.strip()})


def _parse_int_list(raw: str, fallback: int) -> list[int]:
    if not raw:
        return [int(fallback)]
    return sorted({int(v.strip()) for v in raw.split(",") if v.strip()})


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--input", default="input/intraday")
    p.add_argument("--output", default="output/fixed_stop_50")
    p.add_argument("--stop-pct", type=float, default=0.50)
    p.add_argument("--stop-sweep", default="")
    p.add_argument("--slip-bps", type=float, default=20.0)
    p.add_argument("--hold-minutes", type=int, default=45)
    p.add_argument("--hold-sweep", default="")
    p.add_argument("--feed", default="sip")
    a = p.parse_args()

    outdir = Path(a.output)
    outdir.mkdir(parents=True, exist_ok=True)
    trades, coarse = _load_inputs(Path(a.input))
    candidates = select_frozen_candidates(trades, coarse)
    sessions = 60
    expected = {
        "SSR_FLUSH_RECLAIM_RISK_3_5": 136,
        "FAILED_HOD_BREAK_30_50_MIDDAY": 97,
        "POP_AND_DROP_EXTREME_75_PLUS": 122,
    }
    got = candidates.groupby("candidate").size().to_dict()
    if got != expected:
        raise RuntimeError(f"frozen candidate counts changed: expected={expected} got={got}")

    _baseline(candidates).to_csv(outdir / "baseline_candidates.csv", index=False)
    client = Alpaca(os.getenv("APCA_API_KEY_ID", ""), os.getenv("APCA_API_SECRET_KEY", ""), a.feed)

    stops = _parse_float_list(a.stop_sweep, a.stop_pct)
    holds = _parse_int_list(a.hold_sweep, a.hold_minutes)
    grid = parameter_grid(stops, holds)
    fixed, missing = replay_parameter_sweep(
        client,
        candidates,
        stop_pcts=stops,
        slip_bps=a.slip_bps,
        holds=holds,
    )

    fixed.to_csv(outdir / "fixed_stop_trades.csv", index=False)
    pd.DataFrame(missing).to_csv(outdir / "missing.csv", index=False)
    m, ms = _write_metrics(fixed, outdir, sessions)

    selected = pd.DataFrame()
    if len(grid) > 1:
        dev = ms[ms["split"].eq("development")].copy()
        best = (
            dev.sort_values(
                ["candidate", "total_pnl_on_1000_each_trade", "profit_factor"],
                ascending=[True, False, False],
            )
            .groupby("candidate", as_index=False)
            .head(1)[["candidate", "stop_pct", "hold_minutes"]]
            .rename(columns={
                "stop_pct": "selected_stop_from_development",
                "hold_minutes": "selected_hold_from_development",
            })
        )
        selected = ms.merge(best, on="candidate", how="inner")
        selected = selected[
            selected["stop_pct"].eq(selected["selected_stop_from_development"])
            & selected["hold_minutes"].eq(selected["selected_hold_from_development"])
        ].copy()
        selected.to_csv(outdir / "selected_parameter_validation.csv", index=False)

    expected_rows = len(candidates) * len(grid)
    summary = {
        "stop_pct": stops,
        "hold_minutes": holds,
        "slip_bps_exit": a.slip_bps,
        "candidate_count": int(len(candidates)),
        "parameter_combinations": int(len(grid)),
        "expected_replays": int(expected_rows),
        "replayed": int(len(fixed)),
        "coverage": float(len(fixed) / expected_rows if expected_rows else 0.0),
        "missing": int(len(missing)),
        "selection_rule": "when sweeping, select max total $ P&L in development only; validation and holdout are reporting-only",
        "target_policy": "original strategy target preserved; fixed stop and maximum hold controlled independently",
        "final_august_2026_08_12_to_2026_08_27": "untouched",
    }
    (outdir / "manifest.json").write_text(json.dumps(summary, indent=2))
    print(m.to_string(index=False))
    if not selected.empty:
        print("\nSELECTED FROM DEVELOPMENT ONLY\n", selected.to_string(index=False))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
