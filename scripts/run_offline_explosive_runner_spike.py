"""Historical research spike only: no orders and no market-data API calls.

Uses a retained SerClick ignition artifact plus the existing GitHub Actions minute-bar
cache to test whether large-target / trailing exits can clear a 10% expectancy hurdle.
The locked test split is never used to select a rule.
"""
from __future__ import annotations

from pathlib import Path
import math
import requests
import numpy as np
import pandas as pd

ET = "America/New_York"


def block_http() -> None:
    def blocked(*args, **kwargs):
        raise RuntimeError("HTTP_DISABLED_OFFLINE_EXPLOSIVE_RUNNER")
    requests.sessions.Session.request = blocked


def read_bars(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    if df.empty:
        return df
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df["timestamp_et"] = df["timestamp"].dt.tz_convert(ET)
    return df.sort_values("timestamp_et").reset_index(drop=True)


def apply_slippage(price: float, side: str, bps: float) -> float:
    mult = 1.0 + float(bps) / 10000.0 if side == "BUY" else 1.0 - float(bps) / 10000.0
    return float(price) * mult


def metrics(returns: pd.Series) -> dict:
    s = pd.to_numeric(returns, errors="coerce").dropna()
    if s.empty:
        return {"n": 0, "expectancy": np.nan, "pf": np.nan, "win_rate": np.nan, "median": np.nan}
    gains = float(s[s > 0].sum())
    losses = float(-s[s < 0].sum())
    pf = math.inf if losses == 0 and gains > 0 else (gains / losses if losses > 0 else np.nan)
    return {
        "n": int(len(s)),
        "expectancy": float(s.mean()),
        "pf": float(pf),
        "win_rate": float((s > 0).mean()),
        "median": float(s.median()),
    }


def slice_bars(bars: pd.DataFrame, entry_ts, hold_minutes: int) -> pd.DataFrame:
    ts = pd.Timestamp(entry_ts)
    ts = ts.tz_localize(ET) if ts.tzinfo is None else ts.tz_convert(ET)
    end = min(ts + pd.Timedelta(minutes=int(hold_minutes)), ts.normalize() + pd.Timedelta(hours=20))
    return bars[(bars["timestamp_et"] >= ts) & (bars["timestamp_et"] < end)].copy()


def simulate_target_stop(
    bars: pd.DataFrame,
    raw_entry: float,
    entry_ts,
    stop_pct: float,
    target_pct: float,
    hold_minutes: int,
    entry_bps: float,
    exit_bps: float,
) -> tuple[float, str]:
    entry = apply_slippage(raw_entry, "BUY", entry_bps)
    x = slice_bars(bars, entry_ts, hold_minutes)
    if x.empty:
        return np.nan, "NO_DATA"
    stop = entry * (1.0 - stop_pct)
    target = entry * (1.0 + target_pct)
    for _, row in x.iterrows():
        o, h, l = float(row.open), float(row.high), float(row.low)
        # Conservative same-bar rule: stop first.
        if l <= stop:
            base = o if o <= stop else stop
            exit_px = apply_slippage(base, "SELL", exit_bps)
            return (exit_px - entry) / entry, "STOP_GAP" if o <= stop else "STOP"
        if h >= target:
            exit_px = apply_slippage(target, "SELL", exit_bps)
            return (exit_px - entry) / entry, "TARGET"
    exit_px = apply_slippage(float(x.iloc[-1].close), "SELL", exit_bps)
    return (exit_px - entry) / entry, "TIME"


def simulate_trailing(
    bars: pd.DataFrame,
    raw_entry: float,
    entry_ts,
    hard_stop_pct: float,
    activation_pct: float,
    trail_pct: float,
    hold_minutes: int,
    entry_bps: float,
    exit_bps: float,
) -> tuple[float, str]:
    entry = apply_slippage(raw_entry, "BUY", entry_bps)
    x = slice_bars(bars, entry_ts, hold_minutes)
    if x.empty:
        return np.nan, "NO_DATA"
    hard_stop = entry * (1.0 - hard_stop_pct)
    prior_peak = entry
    for _, row in x.iterrows():
        o, h, l = float(row.open), float(row.high), float(row.low)
        if l <= hard_stop:
            base = o if o <= hard_stop else hard_stop
            exit_px = apply_slippage(base, "SELL", exit_bps)
            return (exit_px - entry) / entry, "HARD_STOP_GAP" if o <= hard_stop else "HARD_STOP"
        if prior_peak >= entry * (1.0 + activation_pct):
            trail = prior_peak * (1.0 - trail_pct)
            if l <= trail:
                base = o if o <= trail else trail
                exit_px = apply_slippage(base, "SELL", exit_bps)
                return (exit_px - entry) / entry, "TRAIL_GAP" if o <= trail else "TRAIL"
        # Trail is based only on the prior completed bar peak, avoiding same-bar lookahead.
        prior_peak = max(prior_peak, h)
    exit_px = apply_slippage(float(x.iloc[-1].close), "SELL", exit_bps)
    return (exit_px - entry) / entry, "TIME"


def find_ignitions(root: Path) -> Path:
    matches = list(root.glob("**/ignitions_first.csv"))
    if not matches:
        raise RuntimeError(f"No ignitions_first.csv under {root}")
    return matches[0]


def main() -> None:
    block_http()
    artifact_root = Path("data/offline_prior_artifact")
    cache_root = Path("data/cache/serclick_alpaca/minute")
    ignitions = pd.read_csv(find_ignitions(artifact_root))
    ignitions = ignitions[
        ignitions["population"].eq("BOTH")
        & ignitions["ignition_window"].isin(["10:30-15:00", "15:00-16:00", "16:00-20:00"])
    ].copy()
    ignitions["entry_timestamp"] = pd.to_datetime(ignitions["entry_timestamp"], errors="coerce")

    populations = {
        "POST1030": lambda d: pd.Series(True, index=d.index),
        "MIDDAY": lambda d: d["ignition_window"].eq("10:30-15:00"),
        "AFTER_HOURS_DESCRIPTIVE": lambda d: d["ignition_window"].eq("16:00-20:00"),
        # Post-hoc exploratory only; cannot be treated as locked because the feature was inspected earlier.
        "POSTHOC_RET3_GE_1PCT": lambda d: pd.to_numeric(d["ret3"], errors="coerce") >= 0.01,
    }
    target_rules = [
        (s, t, h)
        for s in (0.07, 0.10, 0.15, 0.20)
        for t in (0.30, 0.40, 0.50, 0.75, 1.00)
        for h in (60, 120, 240)
    ]
    trailing_rules = [
        (s, a, tr, h)
        for s in (0.10, 0.15, 0.20)
        for a in (0.10, 0.15, 0.20, 0.30)
        for tr in (0.05, 0.10, 0.15)
        for h in (120, 240)
        if tr < a or a >= 0.20
    ]
    cost_scenarios = ((25, 25), (50, 50))

    bar_cache: dict[tuple[str, str], pd.DataFrame] = {}
    def bars_for(day: str, symbol: str) -> pd.DataFrame:
        key = (day, symbol)
        if key in bar_cache:
            return bar_cache[key]
        p = cache_root / f"{day}_sip.csv.gz"
        if not p.exists():
            bar_cache[key] = pd.DataFrame()
            return bar_cache[key]
        x = read_bars(p)
        x = x[x["symbol"].astype(str).eq(symbol)].copy()
        bar_cache[key] = x
        return x

    rows = []
    for pop_name, pop_fn in populations.items():
        sample = ignitions[pop_fn(ignitions).fillna(False)].copy()
        for sig in sample.to_dict("records"):
            day, symbol = str(sig["date"]), str(sig["symbol"])
            bars = bars_for(day, symbol)
            if bars.empty:
                continue
            for eb, xb in cost_scenarios:
                for stop, target, hold in target_rules:
                    ret, reason = simulate_target_stop(
                        bars, float(sig["entry_raw_open"]), sig["entry_timestamp"],
                        stop, target, hold, eb, xb,
                    )
                    rows.append({
                        "population_variant": pop_name, "split": sig["split"],
                        "rule_family": "TARGET", "rule_id": f"S{int(stop*100):02d}_T{int(target*100):02d}_H{hold}",
                        "entry_bps": eb, "exit_bps": xb, "return_pct": ret, "exit_reason": reason,
                    })
                for stop, activation, trail, hold in trailing_rules:
                    ret, reason = simulate_trailing(
                        bars, float(sig["entry_raw_open"]), sig["entry_timestamp"],
                        stop, activation, trail, hold, eb, xb,
                    )
                    rows.append({
                        "population_variant": pop_name, "split": sig["split"],
                        "rule_family": "TRAIL", "rule_id": f"S{int(stop*100):02d}_A{int(activation*100):02d}_TR{int(trail*100):02d}_H{hold}",
                        "entry_bps": eb, "exit_bps": xb, "return_pct": ret, "exit_reason": reason,
                    })

    replay = pd.DataFrame(rows)
    print(f"EXPLOSIVE_REPLAY_ROWS {len(replay)}")
    summaries = []
    for key, g in replay.groupby(["population_variant", "rule_family", "rule_id", "entry_bps", "exit_bps", "split"], sort=True):
        m = metrics(g["return_pct"])
        summaries.append(dict(zip(["population_variant", "rule_family", "rule_id", "entry_bps", "exit_bps", "split"], key)) | m)
    summary = pd.DataFrame(summaries)

    # Select on development + validation only. Locked test is reporting-only.
    base = summary[(summary["entry_bps"] == 25) & (summary["exit_bps"] == 25)].copy()
    shortlist = []
    identities = base[["population_variant", "rule_family", "rule_id"]].drop_duplicates().itertuples(index=False, name=None)
    for identity in identities:
        pop, family, rule = identity
        d = base[(base.population_variant == pop) & (base.rule_family == family) & (base.rule_id == rule) & (base.split == "development")]
        v = base[(base.population_variant == pop) & (base.rule_family == family) & (base.rule_id == rule) & (base.split == "validation")]
        if d.empty or v.empty:
            continue
        dr, vr = d.iloc[0], v.iloc[0]
        # AH is shown descriptively but cannot qualify because sample is too small.
        min_dev, min_val = (15, 8) if pop != "AFTER_HOURS_DESCRIPTIVE" else (999, 999)
        qualifies = (
            int(dr.n) >= min_dev and int(vr.n) >= min_val
            and float(dr.expectancy) >= 0.10 and float(vr.expectancy) >= 0.10
            and float(dr.pf) >= 1.5 and float(vr.pf) >= 1.5
        )
        shortlist.append({
            "population_variant": pop, "rule_family": family, "rule_id": rule,
            "development_n": int(dr.n), "development_expectancy": float(dr.expectancy), "development_pf": float(dr.pf),
            "validation_n": int(vr.n), "validation_expectancy": float(vr.expectancy), "validation_pf": float(vr.pf),
            "expectancy_floor": min(float(dr.expectancy), float(vr.expectancy)),
            "pf_floor": min(float(dr.pf), float(vr.pf)), "qualifies_10pct": bool(qualifies),
        })
    ranked = pd.DataFrame(shortlist).sort_values(["qualifies_10pct", "expectancy_floor", "pf_floor"], ascending=[False, False, False])
    print("EXPLOSIVE_DEV_VAL_TOP20")
    print(ranked.head(20).to_string(index=False))

    qualifying = ranked[ranked["qualifies_10pct"]].copy()
    print(f"EXPLOSIVE_10PCT_QUALIFIERS {len(qualifying)}")
    if not qualifying.empty:
        revealed = []
        for r in qualifying.to_dict("records"):
            t = base[(base.population_variant == r["population_variant"]) & (base.rule_family == r["rule_family"]) & (base.rule_id == r["rule_id"]) & (base.split == "test")]
            if t.empty:
                continue
            tr = t.iloc[0]
            revealed.append(r | {"test_n": int(tr.n), "test_expectancy": float(tr.expectancy), "test_pf": float(tr.pf), "test_win_rate": float(tr.win_rate)})
        print("EXPLOSIVE_LOCKED_TEST_REVEAL")
        print(pd.DataFrame(revealed).sort_values("test_expectancy", ascending=False).to_string(index=False))
    else:
        print("NO_RULE_CLEARED_10PCT_IN_BOTH_DEVELOPMENT_AND_VALIDATION")

    # Descriptive AH and 50/50 cost stress are printed separately and never qualify production.
    descriptive = summary[
        (summary["population_variant"] == "AFTER_HOURS_DESCRIPTIVE")
        & (summary["split"].isin(["development", "validation", "test"]))
        & (summary["entry_bps"] == 25) & (summary["exit_bps"] == 25)
    ].sort_values("expectancy", ascending=False).head(20)
    print("AFTER_HOURS_DESCRIPTIVE_TOP20")
    print(descriptive.to_string(index=False))

    stress_ids = ranked.head(5)[["population_variant", "rule_family", "rule_id"]] if not ranked.empty else pd.DataFrame()
    if not stress_ids.empty:
        stress = summary.merge(stress_ids, on=["population_variant", "rule_family", "rule_id"], how="inner")
        stress = stress[(stress.entry_bps == 50) & (stress.exit_bps == 50)]
        print("TOP5_50BPS_ROUNDTRIP_STRESS")
        print(stress.sort_values(["population_variant", "rule_id", "split"]).to_string(index=False))


if __name__ == "__main__":
    main()
