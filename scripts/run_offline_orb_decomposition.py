from __future__ import annotations

from itertools import combinations
from pathlib import Path
from datetime import time

import numpy as np
import pandas as pd

from scanner.core.features import prepare_intraday_bars
from scanner.core.replay import ReplayRule, apply_entry_slippage, simulate_trade
from scanner.core.validation import chronological_split
from scanner.multistrategy.config import MultiStrategyConfig
from scanner.multistrategy.study import broad_candidate_context
from scanner.strategies.orb_stocks_in_play.strategy import generate_orb_signals
from scripts.run_offline_cached_replay import _block_http, _read_bars, _daily_prior_close, _opening30_rvol_map


def _pf(values: pd.Series) -> float:
    x = pd.to_numeric(values, errors="coerce").dropna()
    pos = float(x[x > 0].sum())
    neg = float(x[x < 0].sum())
    if neg == 0:
        return float("inf") if pos > 0 else 0.0
    return pos / abs(neg)


def _metrics(group: pd.DataFrame) -> dict[str, float]:
    r = pd.to_numeric(group["return_pct"], errors="coerce").dropna()
    if r.empty:
        return {"n": 0, "pf": np.nan, "expectancy": np.nan, "median": np.nan, "win_rate": np.nan}
    return {
        "n": int(len(r)),
        "pf": float(_pf(r)),
        "expectancy": float(r.mean()),
        "median": float(r.median()),
        "win_rate": float((r > 0).mean()),
    }


def _contexts(cache: Path) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    minute_files = sorted((cache / "minute").glob("*_sip.csv.gz"))
    early_files = sorted((cache / "early").glob("*_sip.csv.gz"))
    if not minute_files or not early_files:
        raise RuntimeError("missing restored cache")

    dates = sorted({p.name.split("_sip.csv.gz")[0] for p in early_files})
    cfg = MultiStrategyConfig()
    split_map = chronological_split(
        [pd.Timestamp(d).date() for d in dates],
        cfg.development_sessions,
        cfg.validation_sessions,
        cfg.test_sessions,
    )

    bars_by_day: dict[str, pd.DataFrame] = {}
    symbols_by_day: dict[str, set[str]] = {}
    union: set[str] = set()
    for path in minute_files:
        day = path.name.split("_sip.csv.gz")[0]
        bars = _read_bars(path)
        bars_by_day[day] = bars
        syms = set(bars["symbol"].astype(str)) if not bars.empty else set()
        symbols_by_day[day] = syms
        union.update(syms)

    prior_close = _daily_prior_close(cache, union)
    rvol_map = _opening30_rvol_map(cache, union, cfg.opening_baseline_sessions)

    rows: list[dict] = []
    for path in early_files:
        day = path.name.split("_sip.csv.gz")[0]
        day_syms = symbols_by_day.get(day, set())
        if not day_syms:
            continue
        early = _read_bars(path)
        early = early[early["symbol"].astype(str).isin(day_syms)]
        if early.empty:
            continue
        early = prepare_intraday_bars(early)
        d = pd.Timestamp(day).date()
        for symbol, group in early.groupby("symbol", sort=False):
            symbol = str(symbol)
            pc = prior_close.get((symbol, d))
            if pc is None:
                continue
            ctx = broad_candidate_context(group, pc, cfg)
            if not ctx.get("broad_candidate"):
                continue
            rv = rvol_map.get((symbol, day))
            if rv is None:
                continue
            rvol, history_n = rv
            ctx.update({
                "symbol": symbol,
                "date": day,
                "split": split_map[d],
                "feed": "SIP",
                "market_cap": np.nan,
                "market_cap_bucket": "UNKNOWN",
                "opening_rvol": float(rvol),
                "opening_rvol_history_n": int(history_n),
                "catalyst_class": "UNKNOWN",
            })
            rows.append(ctx)
    return pd.DataFrame(rows), bars_by_day


def _signal_table(contexts: pd.DataFrame, bars_by_day: dict[str, pd.DataFrame]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for day, group in contexts.groupby("date", sort=True) if not contexts.empty else []:
        minute = bars_by_day.get(str(day), pd.DataFrame())
        if minute.empty:
            continue
        for ctx in group.to_dict("records"):
            symbol = str(ctx["symbol"])
            bars = minute[minute["symbol"].astype(str).eq(symbol)].copy()
            if bars.empty:
                continue
            out = generate_orb_signals(bars, ctx)
            if out.empty:
                continue
            out = out[out["variant_id"].eq("ORB_LONG_BREAK")].copy()
            if out.empty:
                continue
            out["prior_close"] = float(ctx["prior_close"])
            out["pm_gap_pct"] = float(ctx["pm_gap_pct"])
            out["pm_dollar_turnover"] = float(ctx["pm_dollar_turnover"])
            out["opening_rvol"] = float(ctx["opening_rvol"])
            frames.append(out)
    signals = pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()
    if signals.empty:
        return signals

    def setup_value(value, key, default=np.nan):
        if isinstance(value, dict):
            return value.get(key, default)
        return default

    signals["breakout_volume_ratio"] = signals["setup_metadata"].map(lambda v: setup_value(v, "volume_ratio"))
    signals["breakout_clv"] = signals["setup_metadata"].map(lambda v: setup_value(v, "clv"))
    signals["or_high"] = signals["setup_metadata"].map(lambda v: setup_value(v, "opening_range_high"))
    signals["or_low"] = signals["setup_metadata"].map(lambda v: setup_value(v, "opening_range_low"))
    signals["or_width_pct"] = (pd.to_numeric(signals["or_high"], errors="coerce") - pd.to_numeric(signals["or_low"], errors="coerce")) / pd.to_numeric(signals["prior_close"], errors="coerce")
    ts = pd.to_datetime(signals["signal_timestamp"], utc=True, errors="coerce").dt.tz_convert("America/New_York")
    signals["entry_minutes"] = ts.dt.hour * 60 + ts.dt.minute
    return signals


def _replay(signals: pd.DataFrame, bars_by_day: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows: list[dict] = []
    for sig in signals.to_dict("records"):
        day = str(sig["date"])
        minute = bars_by_day.get(day, pd.DataFrame())
        bars = minute[minute["symbol"].astype(str).eq(str(sig["symbol"]))].copy()
        if bars.empty:
            continue
        entry = apply_entry_slippage(float(sig["entry_price_raw"]), "LONG", 25.0)
        for hold in (15, 30, 60, 120):
            result = simulate_trade(
                bars,
                entry,
                sig["entry_timestamp"],
                "LONG",
                ReplayRule(max_hold_minutes=hold),
                session_end="16:00",
            )
            rows.append({
                **{k: sig.get(k) for k in [
                    "symbol", "date", "split", "prior_close", "pm_gap_pct", "pm_dollar_turnover",
                    "opening_rvol", "breakout_volume_ratio", "breakout_clv", "or_width_pct", "entry_minutes"
                ]},
                "hold_minutes": hold,
                "return_pct": result.return_pct,
                "mfe_pct": result.mfe_pct,
                "mae_pct": result.mae_pct,
            })
    return pd.DataFrame(rows)


def _filter_specs() -> list[tuple[str, str, float]]:
    specs: list[tuple[str, str, float]] = []
    specs += [("gap", "pm_gap_pct", x) for x in (0.05, 0.08, 0.10, 0.15, 0.20)]
    specs += [("rvol", "opening_rvol", x) for x in (3.0, 5.0, 10.0)]
    specs += [("turnover", "pm_dollar_turnover", x) for x in (1_000_000.0, 2_000_000.0, 5_000_000.0, 10_000_000.0)]
    specs += [("volratio", "breakout_volume_ratio", x) for x in (1.5, 2.0, 3.0)]
    specs += [("clv", "breakout_clv", x) for x in (0.60, 0.70, 0.75, 0.80)]
    # For these two dimensions lower is stricter/better: earlier entry and tighter opening range.
    specs += [("entrymax", "entry_minutes", x) for x in (9*60+45, 10*60, 10*60+30, 11*60, 12*60)]
    specs += [("orwidthmax", "or_width_pct", x) for x in (0.05, 0.10, 0.15, 0.20, 0.30)]
    return specs


def _apply_filter(frame: pd.DataFrame, spec: tuple[str, str, float]) -> pd.Series:
    family, col, threshold = spec
    x = pd.to_numeric(frame[col], errors="coerce")
    if family in {"entrymax", "orwidthmax"}:
        return x <= threshold
    return x >= threshold


def _label(spec: tuple[str, str, float]) -> str:
    family, _, value = spec
    if family == "turnover":
        return f"turnover>={value/1_000_000:g}m"
    if family == "entrymax":
        return f"entry<={int(value)//60:02d}:{int(value)%60:02d}"
    if family == "orwidthmax":
        return f"orwidth<={value:.0%}"
    if family in {"gap"}:
        return f"gap>={value:.0%}"
    return f"{family}>={value:g}"


def _candidate_filters() -> list[tuple[tuple[str, str, float], ...]]:
    specs = _filter_specs()
    candidates = [(s,) for s in specs]
    # Pair only different dimensions; avoid nonsensical same-family threshold pairs.
    for a, b in combinations(specs, 2):
        if a[0] != b[0]:
            candidates.append((a, b))
    return candidates


def main() -> None:
    _block_http()
    cache = Path("data/cache/serclick_alpaca")
    contexts, bars_by_day = _contexts(cache)
    signals = _signal_table(contexts, bars_by_day)
    print(f"ORB_DECOMP_CONTEXTS {len(contexts)}", flush=True)
    print(f"ORB_LONG_BREAK_SIGNALS {len(signals)}", flush=True)
    if signals.empty:
        return

    print("ORB_SIGNAL_SPLITS", flush=True)
    print(signals.groupby("split").size().to_string(), flush=True)

    replay = _replay(signals, bars_by_day)
    if replay.empty:
        print("NO_REPLAY", flush=True)
        return

    print("ORB_BASELINE_25BPS", flush=True)
    base_rows = []
    for hold in (15, 30, 60, 120):
        row = {"hold": hold}
        for split in ("development", "validation", "test"):
            m = _metrics(replay[(replay["hold_minutes"].eq(hold)) & (replay["split"].eq(split))])
            row[f"{split}_n"] = m["n"]
            row[f"{split}_pf"] = m["pf"]
            row[f"{split}_exp"] = m["expectancy"]
        base_rows.append(row)
    print(pd.DataFrame(base_rows).to_string(index=False), flush=True)

    selected_rows: list[dict] = []
    for hold in (15, 30, 60, 120):
        h = replay[replay["hold_minutes"].eq(hold)].copy()
        for specs in _candidate_filters():
            mask = pd.Series(True, index=h.index)
            for spec in specs:
                mask &= _apply_filter(h, spec)
            filtered = h[mask]
            dev = _metrics(filtered[filtered["split"].eq("development")])
            val = _metrics(filtered[filtered["split"].eq("validation")])
            # Selection is development + validation only. Test is not consulted here.
            if dev["n"] < 10 or val["n"] < 20:
                continue
            if not (dev["pf"] > 1.0 and dev["expectancy"] > 0 and val["pf"] > 1.0 and val["expectancy"] > 0):
                continue
            robust_pf = min(dev["pf"], val["pf"])
            robust_exp = min(dev["expectancy"], val["expectancy"])
            selected_rows.append({
                "filter": " & ".join(_label(s) for s in specs),
                "hold": hold,
                "dev_n": dev["n"], "dev_pf": dev["pf"], "dev_exp": dev["expectancy"], "dev_wr": dev["win_rate"],
                "val_n": val["n"], "val_pf": val["pf"], "val_exp": val["expectancy"], "val_wr": val["win_rate"],
                "robust_pf": robust_pf,
                "robust_exp": robust_exp,
            })

    selected = pd.DataFrame(selected_rows)
    if selected.empty:
        print("ORB_ROBUST_FILTERS none", flush=True)
        return

    selected = selected.sort_values(["robust_pf", "robust_exp", "val_n"], ascending=[False, False, False]).reset_index(drop=True)
    # Deduplicate near-identical results by keeping the first occurrence of each filter+hold.
    selected = selected.drop_duplicates(["filter", "hold"])

    print("ORB_SELECTED_WITHOUT_TEST_TOP20", flush=True)
    print(selected.head(20).to_string(index=False), flush=True)

    # Only now expose locked test results for the development/validation-selected candidates.
    test_rows: list[dict] = []
    for _, candidate in selected.head(20).iterrows():
        specs = None
        label = str(candidate["filter"])
        for candidate_specs in _candidate_filters():
            if " & ".join(_label(s) for s in candidate_specs) == label:
                specs = candidate_specs
                break
        if specs is None:
            continue
        h = replay[replay["hold_minutes"].eq(int(candidate["hold"]))].copy()
        mask = pd.Series(True, index=h.index)
        for spec in specs:
            mask &= _apply_filter(h, spec)
        test = _metrics(h[mask & h["split"].eq("test")])
        test_rows.append({
            **candidate.to_dict(),
            "test_n": test["n"], "test_pf": test["pf"], "test_exp": test["expectancy"], "test_wr": test["win_rate"],
            "survives_test": bool(test["n"] >= 20 and test["pf"] > 1.0 and test["expectancy"] > 0),
        })

    tested = pd.DataFrame(test_rows)
    print("ORB_LOCKED_TEST_RESULTS", flush=True)
    print(tested.to_string(index=False), flush=True)

    survivors = tested[tested["survives_test"]].copy()
    print(f"ORB_TEST_SURVIVORS {len(survivors)}", flush=True)
    if not survivors.empty:
        survivors["all_split_pf_floor"] = survivors[["dev_pf", "val_pf", "test_pf"]].min(axis=1)
        survivors["all_split_exp_floor"] = survivors[["dev_exp", "val_exp", "test_exp"]].min(axis=1)
        survivors = survivors.sort_values(["all_split_pf_floor", "all_split_exp_floor", "test_n"], ascending=[False, False, False])
        print("ORB_SURVIVOR_RANKING", flush=True)
        print(survivors.head(10).to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
