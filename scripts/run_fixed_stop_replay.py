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

    out = pd.concat([ssr, fh], ignore_index=True)
    out["entry_ts"] = pd.to_datetime(out["entry_ts"], utc=True)
    return out.sort_values(["session_date", "candidate", "ticker"]).reset_index(drop=True)


def _metric_rows(df: pd.DataFrame, sessions: int, label: str) -> list[dict]:
    rows = []
    for candidate, g in df.groupby("candidate"):
        v = pd.to_numeric(g["return_pct"], errors="coerce").dropna()
        pos = float(v[v > 0].sum())
        neg = float(-v[v < 0].sum())
        pf = pos / neg if neg > 0 else (float("inf") if pos > 0 else 0.0)
        eq = pd.Series([0.0] + v.cumsum().tolist())
        max_dd = float((eq.cummax() - eq).max())
        rows.append(
            {
                "variant": label,
                "candidate": candidate,
                "n": int(len(v)),
                "trades_per_day": float(len(v) / max(1, sessions)),
                "profit_factor": float(pf),
                "avg_return_pct": float(v.mean()),
                "win_rate": float((v > 0).mean()),
                "max_drawdown_pct_points": max_dd,
                "avg_pnl_on_1000": float(v.mean() * 1000.0),
                "total_pnl_on_1000_each_trade": float(v.sum() * 1000.0),
            }
        )
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


def replay(
    client: Alpaca,
    candidates: pd.DataFrame,
    *,
    stop_pct: float,
    slip_bps: float,
    hold_minutes: int,
) -> tuple[pd.DataFrame, list[dict]]:
    out = []
    missing = []

    for session_date, day in candidates.groupby("session_date", sort=True):
        symbols = sorted(day["ticker"].unique().tolist())
        start = day["entry_ts"].min().to_pydatetime()
        d = pd.Timestamp(session_date).date()
        market_close = datetime(d.year, d.month, d.day, 16, 1, tzinfo=NY).astimezone(start.tzinfo)
        wanted_end = (day["entry_ts"].max() + pd.Timedelta(minutes=hold_minutes + 1)).to_pydatetime()
        end = min(wanted_end, market_close)
        bars = client.bars(symbols, "1Min", start, end, str(session_date))

        for _, row in day.iterrows():
            raw = bars.get(str(row.ticker).upper(), [])
            if not raw:
                missing.append({"session_date": session_date, "ticker": row.ticker, "candidate": row.candidate, "reason": "NO_BARS"})
                continue

            b = pd.DataFrame(raw)
            rename = {"t": "timestamp", "o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"}
            b = b.rename(columns=rename)
            if "timestamp" not in b.columns:
                missing.append({"session_date": session_date, "ticker": row.ticker, "candidate": row.candidate, "reason": "NO_TIMESTAMP"})
                continue
            b["timestamp"] = pd.to_datetime(b["timestamp"], utc=True)
            e0 = pd.Timestamp(row.entry_ts)
            b = b[b["timestamp"] >= e0].copy()
            if b.empty:
                missing.append({"session_date": session_date, "ticker": row.ticker, "candidate": row.candidate, "reason": "EMPTY_WINDOW"})
                continue

            r = simulate_fixed_stop(
                b,
                side=str(row.side),
                entry=float(row.entry),
                target=float(row.target),
                stop_pct=stop_pct,
                slip_bps=slip_bps,
                hold_minutes=hold_minutes,
            )
            out.append(
                {
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
                    "stop_pct": stop_pct,
                    "hold_minutes": hold_minutes,
                }
            )

    return pd.DataFrame(out), missing


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--input", default="input/intraday")
    p.add_argument("--output", default="output/fixed_stop_50")
    p.add_argument("--stop-pct", type=float, default=0.50)
    p.add_argument("--slip-bps", type=float, default=20.0)
    p.add_argument("--hold-minutes", type=int, default=45)
    p.add_argument("--feed", default="sip")
    a = p.parse_args()

    root = Path(a.input)
    outdir = Path(a.output)
    outdir.mkdir(parents=True, exist_ok=True)

    trades, coarse = _load_inputs(root)
    candidates = select_frozen_candidates(trades, coarse)
    sessions = 60
    expected = {"SSR_FLUSH_RECLAIM_RISK_3_5": 136, "FAILED_HOD_BREAK_30_50_MIDDAY": 97}
    got = candidates.groupby("candidate").size().to_dict()
    if got != expected:
        raise RuntimeError(f"frozen candidate counts changed: expected={expected} got={got}")

    baseline = _baseline(candidates)
    baseline.to_csv(outdir / "baseline_candidates.csv", index=False)

    client = Alpaca(
        os.getenv("APCA_API_KEY_ID", ""),
        os.getenv("APCA_API_SECRET_KEY", ""),
        a.feed,
    )
    fixed, missing = replay(
        client,
        candidates,
        stop_pct=a.stop_pct,
        slip_bps=a.slip_bps,
        hold_minutes=a.hold_minutes,
    )
    fixed.to_csv(outdir / "fixed_stop_trades.csv", index=False)
    pd.DataFrame(missing).to_csv(outdir / "missing.csv", index=False)

    metrics = []
    metrics.extend(_metric_rows(baseline, sessions, "ORIGINAL_STRUCTURAL_STOP"))
    label = f"FIXED_STOP_{a.stop_pct:.0%}_HOLD_{a.hold_minutes}m"
    metrics.extend(_metric_rows(fixed, sessions, label))
    m = pd.DataFrame(metrics)
    m.to_csv(outdir / "metrics.csv", index=False)

    split_rows = []
    for split, g in fixed.groupby("split"):
        for r in _metric_rows(g, max(1, g["session_date"].nunique()), label):
            r["split"] = split
            split_rows.append(r)
    pd.DataFrame(split_rows).to_csv(outdir / "metrics_splits.csv", index=False)

    coverage = len(fixed) / len(candidates) if len(candidates) else 0.0
    summary = {
        "stop_pct": a.stop_pct,
        "hold_minutes": a.hold_minutes,
        "slip_bps_exit": a.slip_bps,
        "candidate_count": int(len(candidates)),
        "replayed": int(len(fixed)),
        "coverage": coverage,
        "missing": int(len(missing)),
        "target_policy": "original strategy target preserved; stop and maximum hold are controlled independently",
        "final_august_2026_08_12_to_2026_08_27": "untouched",
    }
    (outdir / "manifest.json").write_text(json.dumps(summary, indent=2))
    print(m.to_string(index=False))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
