"""Historical research only. Uses restored cached bars; no orders and no market-data API calls."""
from pathlib import Path
import numpy as np
import pandas as pd
from scanner.core.replay import apply_entry_slippage
from scripts.run_offline_cached_replay import _block_http
from scripts.run_offline_orb_decomposition import _contexts, _signal_table, _metrics

ET = "America/New_York"


def trade_return(bars, raw_entry, entry_timestamp, entry_bps, exit_bps):
    entry = apply_entry_slippage(float(raw_entry), "LONG", float(entry_bps))
    x = bars.copy()
    x["timestamp"] = pd.to_datetime(x["timestamp"], utc=True, errors="coerce")
    x["timestamp_et"] = x["timestamp"].dt.tz_convert(ET)
    ts = pd.Timestamp(entry_timestamp)
    ts = ts.tz_localize(ET) if ts.tzinfo is None else ts.tz_convert(ET)
    x = x[(x["timestamp_et"] >= ts) & (x["timestamp_et"] <= ts + pd.Timedelta(minutes=15))].sort_values("timestamp_et")
    if x.empty:
        return np.nan, "NO_DATA"
    stop = entry * 0.90
    target = entry * 1.05
    exit_slip = 1.0 - float(exit_bps) / 10000.0
    for _, row in x.iterrows():
        o, h, l = float(row["open"]), float(row["high"]), float(row["low"])
        if l <= stop:
            base = o if o <= stop else stop
            return (base * exit_slip - entry) / entry, "STOP_GAP" if o <= stop else "STOP"
        if h >= target:
            return (target - entry) / entry, "TARGET"
    return (float(x.iloc[-1]["close"]) * exit_slip - entry) / entry, "TIME"


def main():
    _block_http()
    contexts, bars_by_day = _contexts(Path("data/cache/serclick_alpaca"))
    signals = _signal_table(contexts, bars_by_day)
    mask = (pd.to_numeric(signals["or_width_pct"], errors="coerce") <= 0.15) & (pd.to_numeric(signals["breakout_clv"], errors="coerce") >= 0.70)
    signals = signals[mask].copy()
    scenarios = ((10,10),(25,10),(25,25),(50,25),(50,50),(75,50),(75,75),(100,100))
    rows = []
    for sig in signals.to_dict("records"):
        day = str(sig["date"])
        daybars = bars_by_day.get(day, pd.DataFrame())
        bars = daybars[daybars["symbol"].astype(str).eq(str(sig["symbol"]))].copy()
        for eb, xb in scenarios:
            ret, reason = trade_return(bars, sig["entry_price_raw"], sig["entry_timestamp"], eb, xb)
            rows.append({"split":sig["split"],"entry_bps":eb,"exit_bps":xb,"return_pct":ret,"reason":reason})
    replay = pd.DataFrame(rows)
    out = []
    for (split, eb, xb), g in replay.groupby(["split","entry_bps","exit_bps"], sort=True):
        m = _metrics(g)
        exits = g["reason"].value_counts().to_dict()
        out.append({"split":split,"entry_bps":eb,"exit_bps":xb,"n":m["n"],"pf":m["pf"],"expectancy":m["expectancy"],"win_rate":m["win_rate"],"targets":exits.get("TARGET",0),"stops":exits.get("STOP",0),"gap_stops":exits.get("STOP_GAP",0),"time_exits":exits.get("TIME",0)})
    summary = pd.DataFrame(out)
    print("ORB_EXECUTION_STRESS")
    print(summary.to_string(index=False))
    print("ORB_EXECUTION_FLOORS")
    floors=[]
    for (eb,xb),g in summary.groupby(["entry_bps","exit_bps"],sort=True):
        floors.append({"entry_bps":eb,"exit_bps":xb,"pf_floor":g["pf"].min(),"expectancy_floor":g["expectancy"].min(),"all_splits_positive":bool((g["pf"]>1).all() and (g["expectancy"]>0).all())})
    print(pd.DataFrame(floors).to_string(index=False))

if __name__ == "__main__":
    main()
