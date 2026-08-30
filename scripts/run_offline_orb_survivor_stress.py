from __future__ import annotations

from pathlib import Path

import pandas as pd

from scanner.core.replay import ReplayRule, apply_entry_slippage, simulate_trade
from scripts.run_offline_cached_replay import _block_http
from scripts.run_offline_orb_decomposition import _contexts, _signal_table, _metrics


def _candidate_mask(signals: pd.DataFrame, name: str) -> pd.Series:
    width = pd.to_numeric(signals["or_width_pct"], errors="coerce") <= 0.15
    if name == "CLV70_WIDTH15_H15":
        return width & (pd.to_numeric(signals["breakout_clv"], errors="coerce") >= 0.70)
    if name == "WIDTH15_H15":
        return width
    if name == "EARLY0945_WIDTH15_H30":
        return width & (pd.to_numeric(signals["entry_minutes"], errors="coerce") <= 9 * 60 + 45)
    if name == "EARLY1030_WIDTH15_H15":
        return width & (pd.to_numeric(signals["entry_minutes"], errors="coerce") <= 10 * 60 + 30)
    if name == "CLV75_WIDTH15_H15":
        return width & (pd.to_numeric(signals["breakout_clv"], errors="coerce") >= 0.75)
    raise ValueError(name)


def main() -> None:
    _block_http()
    cache = Path("data/cache/serclick_alpaca")
    contexts, bars_by_day = _contexts(cache)
    signals = _signal_table(contexts, bars_by_day)
    if signals.empty:
        print("NO_SIGNALS", flush=True)
        return

    candidates = {
        "CLV70_WIDTH15_H15": 15,
        "WIDTH15_H15": 15,
        "EARLY0945_WIDTH15_H30": 30,
        "EARLY1030_WIDTH15_H15": 15,
        "CLV75_WIDTH15_H15": 15,
    }
    bps_grid = (10.0, 25.0, 50.0, 75.0, 100.0)
    rows: list[dict] = []

    for name, hold in candidates.items():
        subset = signals[_candidate_mask(signals, name)].copy()
        for sig in subset.to_dict("records"):
            day = str(sig["date"])
            minute = bars_by_day.get(day, pd.DataFrame())
            bars = minute[minute["symbol"].astype(str).eq(str(sig["symbol"]))].copy()
            if bars.empty:
                continue
            for bps in bps_grid:
                entry = apply_entry_slippage(float(sig["entry_price_raw"]), "LONG", bps)
                result = simulate_trade(
                    bars,
                    entry,
                    sig["entry_timestamp"],
                    "LONG",
                    ReplayRule(max_hold_minutes=hold),
                    session_end="16:00",
                )
                rows.append({
                    "candidate": name,
                    "hold": hold,
                    "symbol": sig["symbol"],
                    "date": day,
                    "split": sig["split"],
                    "slippage_bps": bps,
                    "return_pct": result.return_pct,
                })

    replay = pd.DataFrame(rows)
    if replay.empty:
        print("NO_REPLAY", flush=True)
        return

    print("ORB_SURVIVOR_SLIPPAGE_STRESS", flush=True)
    summary_rows: list[dict] = []
    for keys, group in replay.groupby(["candidate", "hold", "split", "slippage_bps"], sort=True):
        candidate, hold, split, bps = keys
        m = _metrics(group)
        sessions = {"development": 30, "validation": 15, "test": 15}.get(str(split), 15)
        summary_rows.append({
            "candidate": candidate,
            "hold": int(hold),
            "split": split,
            "bps": float(bps),
            "n": m["n"],
            "trades_per_day": m["n"] / sessions if sessions else 0.0,
            "pf": m["pf"],
            "expectancy": m["expectancy"],
            "win_rate": m["win_rate"],
            "avg_pnl_gbp_1000": m["expectancy"] * 1000.0,
            "avg_pnl_gbp_2000": m["expectancy"] * 2000.0,
            "avg_pnl_gbp_3000": m["expectancy"] * 3000.0,
        })
    summary = pd.DataFrame(summary_rows)
    print(summary.to_string(index=False), flush=True)

    print("ORB_TEST_SLIPPAGE_FLOORS", flush=True)
    test = summary[summary["split"].eq("test")].copy()
    for candidate, group in test.groupby("candidate", sort=False):
        profitable = group[(group["pf"] > 1.0) & (group["expectancy"] > 0)]
        last = float(profitable["bps"].max()) if not profitable.empty else float("nan")
        b25 = group[group["bps"].eq(25.0)]
        row25 = b25.iloc[0] if len(b25) else None
        if row25 is None:
            continue
        print(
            f"{candidate} test_n={int(row25['n'])} pf25={row25['pf']:.3f} exp25={row25['expectancy']:.4f} "
            f"wr25={row25['win_rate']:.3f} last_profitable_bps={last:g}",
            flush=True,
        )


if __name__ == "__main__":
    main()
