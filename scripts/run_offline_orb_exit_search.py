from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from scanner.core.replay import ReplayRule, apply_entry_slippage, simulate_trade
from scripts.run_offline_cached_replay import _block_http
from scripts.run_offline_orb_decomposition import _contexts, _signal_table, _metrics


@dataclass(frozen=True)
class NamedRule:
    name: str
    rule: ReplayRule


def _rules() -> list[NamedRule]:
    out: list[NamedRule] = []
    for hold in (15, 30):
        out.append(NamedRule(f"TIME_H{hold}", ReplayRule(max_hold_minutes=hold)))
        for stop in (0.03, 0.05, 0.07, 0.10, 0.15, 0.20):
            out.append(NamedRule(f"S{int(stop*100):02d}_TIME_H{hold}", ReplayRule(stop_pct=stop, max_hold_minutes=hold)))
            for target in (0.05, 0.10, 0.15, 0.20, 0.30):
                out.append(NamedRule(
                    f"S{int(stop*100):02d}_T{int(target*100):02d}_H{hold}",
                    ReplayRule(stop_pct=stop, target_pct=target, max_hold_minutes=hold),
                ))
        out.append(NamedRule(f"SSTRUCT_TIME_H{hold}", ReplayRule(stop_price=1.0, max_hold_minutes=hold)))
        for r in (1.0, 1.5, 2.0, 3.0):
            out.append(NamedRule(f"SSTRUCT_R{r:g}_H{hold}", ReplayRule(stop_price=1.0, target_r_multiple=r, max_hold_minutes=hold)))
    return out


def _max_drawdown(returns: pd.Series) -> float:
    r = pd.to_numeric(returns, errors="coerce").dropna()
    if r.empty:
        return np.nan
    equity = (1.0 + r).cumprod()
    peak = equity.cummax()
    dd = equity / peak - 1.0
    return float(dd.min())


def main() -> None:
    _block_http()
    cache = Path("data/cache/serclick_alpaca")
    contexts, bars_by_day = _contexts(cache)
    signals = _signal_table(contexts, bars_by_day)
    if signals.empty:
        print("NO_SIGNALS", flush=True)
        return

    width = pd.to_numeric(signals["or_width_pct"], errors="coerce") <= 0.15
    clv = pd.to_numeric(signals["breakout_clv"], errors="coerce") >= 0.70
    signals = signals[width & clv].copy()
    print("ORB_EXIT_FILTER CLV>=0.70 AND OPENING_RANGE_WIDTH<=15%", flush=True)
    print(signals.groupby("split").size().to_string(), flush=True)

    named_rules = _rules()
    rows: list[dict] = []
    for sig in signals.to_dict("records"):
        day = str(sig["date"])
        minute = bars_by_day.get(day, pd.DataFrame())
        bars = minute[minute["symbol"].astype(str).eq(str(sig["symbol"]))].copy()
        if bars.empty:
            continue
        entry = apply_entry_slippage(float(sig["entry_price_raw"]), "LONG", 25.0)
        structural = float(sig["stop_reference"]) if pd.notna(sig.get("stop_reference")) else np.nan
        for named in named_rules:
            rule = named.rule
            if named.name.startswith("SSTRUCT"):
                if not np.isfinite(structural) or structural <= 0 or structural >= entry:
                    continue
                rule = ReplayRule(
                    stop_price=structural,
                    target_r_multiple=rule.target_r_multiple,
                    max_hold_minutes=rule.max_hold_minutes,
                )
            result = simulate_trade(bars, entry, sig["entry_timestamp"], "LONG", rule, session_end="16:00")
            rows.append({
                "rule": named.name,
                "symbol": sig["symbol"],
                "date": day,
                "split": sig["split"],
                "return_pct": result.return_pct,
                "exit_reason": result.exit_reason,
                "mfe_pct": result.mfe_pct,
                "mae_pct": result.mae_pct,
            })

    replay = pd.DataFrame(rows)
    if replay.empty:
        print("NO_REPLAY", flush=True)
        return

    summaries: list[dict] = []
    for (rule, split), g in replay.groupby(["rule", "split"], sort=False):
        m = _metrics(g)
        r = pd.to_numeric(g["return_pct"], errors="coerce").dropna()
        summaries.append({
            "rule": rule,
            "split": split,
            "n": m["n"],
            "pf": m["pf"],
            "expectancy": m["expectancy"],
            "median": m["median"],
            "win_rate": m["win_rate"],
            "max_drawdown": _max_drawdown(r),
            "worst_trade": float(r.min()) if not r.empty else np.nan,
            "mean_mfe": float(pd.to_numeric(g["mfe_pct"], errors="coerce").mean()),
            "mean_mae": float(pd.to_numeric(g["mae_pct"], errors="coerce").mean()),
        })
    summary = pd.DataFrame(summaries)

    candidates: list[dict] = []
    for rule, g in summary.groupby("rule", sort=False):
        dev = g[g["split"].eq("development")]
        val = g[g["split"].eq("validation")]
        if dev.empty or val.empty:
            continue
        d = dev.iloc[0]
        v = val.iloc[0]
        if int(d["n"]) < 20 or int(v["n"]) < 40:
            continue
        if not (float(d["pf"]) > 1.0 and float(d["expectancy"]) > 0 and float(v["pf"]) > 1.0 and float(v["expectancy"]) > 0):
            continue
        candidates.append({
            "rule": rule,
            "dev_n": int(d["n"]), "dev_pf": float(d["pf"]), "dev_exp": float(d["expectancy"]), "dev_dd": float(d["max_drawdown"]), "dev_worst": float(d["worst_trade"]),
            "val_n": int(v["n"]), "val_pf": float(v["pf"]), "val_exp": float(v["expectancy"]), "val_dd": float(v["max_drawdown"]), "val_worst": float(v["worst_trade"]),
            "pf_floor": min(float(d["pf"]), float(v["pf"])),
            "exp_floor": min(float(d["expectancy"]), float(v["expectancy"])),
            "dd_floor": min(float(d["max_drawdown"]), float(v["max_drawdown"])),
        })

    selected = pd.DataFrame(candidates)
    if selected.empty:
        print("ORB_EXIT_SELECTED none", flush=True)
        return
    selected = selected.sort_values(["pf_floor", "exp_floor", "dd_floor"], ascending=[False, False, False]).reset_index(drop=True)
    print("ORB_EXIT_SELECTED_WITHOUT_TEST_TOP20", flush=True)
    print(selected.head(20).to_string(index=False), flush=True)

    tested: list[dict] = []
    for _, candidate in selected.head(20).iterrows():
        test = summary[(summary["rule"].eq(candidate["rule"])) & (summary["split"].eq("test"))]
        if test.empty:
            continue
        t = test.iloc[0]
        tested.append({
            **candidate.to_dict(),
            "test_n": int(t["n"]),
            "test_pf": float(t["pf"]),
            "test_exp": float(t["expectancy"]),
            "test_wr": float(t["win_rate"]),
            "test_dd": float(t["max_drawdown"]),
            "test_worst": float(t["worst_trade"]),
            "survives_test": bool(float(t["pf"]) > 1.0 and float(t["expectancy"]) > 0),
        })
    tested_df = pd.DataFrame(tested)
    print("ORB_EXIT_LOCKED_TEST", flush=True)
    print(tested_df.to_string(index=False), flush=True)

    survivors = tested_df[tested_df["survives_test"]].copy()
    print(f"ORB_EXIT_SURVIVORS {len(survivors)}", flush=True)
    if not survivors.empty:
        survivors["all_pf_floor"] = survivors[["dev_pf", "val_pf", "test_pf"]].min(axis=1)
        survivors["all_exp_floor"] = survivors[["dev_exp", "val_exp", "test_exp"]].min(axis=1)
        survivors["all_dd_worst"] = survivors[["dev_dd", "val_dd", "test_dd"]].min(axis=1)
        survivors = survivors.sort_values(["all_pf_floor", "all_exp_floor", "all_dd_worst"], ascending=[False, False, False])
        print("ORB_EXIT_SURVIVOR_RANKING", flush=True)
        print(survivors.head(10).to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
