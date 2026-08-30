"""Fast historical scout using retained ignition results + restored minute cache only."""
from __future__ import annotations
from pathlib import Path
import math
import requests
import numpy as np
import pandas as pd

ET = "America/New_York"


def block_http():
    def blocked(*args, **kwargs):
        raise RuntimeError("HTTP_DISABLED_OFFLINE_FAST_SCOUT")
    requests.sessions.Session.request = blocked


def metric(values):
    s = pd.Series(values, dtype=float).dropna()
    if s.empty:
        return dict(n=0, expectancy=np.nan, pf=np.nan, win_rate=np.nan)
    gp = float(s[s > 0].sum()); gl = float(-s[s < 0].sum())
    pf = math.inf if gl == 0 and gp > 0 else (gp / gl if gl > 0 else np.nan)
    return dict(n=len(s), expectancy=float(s.mean()), pf=float(pf), win_rate=float((s > 0).mean()))


def slip(price, side, bps):
    return float(price) * (1 + bps / 10000.0 if side == "BUY" else 1 - bps / 10000.0)


def load_event_bars(cache, row):
    p = cache / f"{row.date}_sip.csv.gz"
    if not p.exists():
        return None
    x = pd.read_csv(p)
    x = x[x.symbol.astype(str).eq(str(row.symbol))].copy()
    if x.empty:
        return None
    x["timestamp"] = pd.to_datetime(x.timestamp, utc=True, errors="coerce")
    x["timestamp_et"] = x.timestamp.dt.tz_convert(ET)
    ts = pd.Timestamp(row.entry_timestamp)
    ts = ts.tz_localize(ET) if ts.tzinfo is None else ts.tz_convert(ET)
    end = ts.normalize() + pd.Timedelta(hours=20)
    x = x[(x.timestamp_et >= ts) & (x.timestamp_et < end)].sort_values("timestamp_et")
    if x.empty:
        return None
    return {
        "ts": x.timestamp_et.to_numpy(),
        "open": x.open.astype(float).to_numpy(),
        "high": x.high.astype(float).to_numpy(),
        "low": x.low.astype(float).to_numpy(),
        "close": x.close.astype(float).to_numpy(),
        "entry_ts": ts,
    }


def target_return(b, raw_entry, stop_pct, target_pct, hold, eb=25, xb=25):
    entry = slip(raw_entry, "BUY", eb)
    cutoff = np.datetime64((b["entry_ts"] + pd.Timedelta(minutes=hold)).tz_localize(None))
    ts_naive = np.array([pd.Timestamp(t).tz_localize(None).to_datetime64() for t in b["ts"]])
    n = int(np.searchsorted(ts_naive, cutoff, side="left"))
    n = max(1, min(n, len(b["close"])))
    o,h,l,c = (b[k][:n] for k in ("open","high","low","close"))
    stop = entry*(1-stop_pct); target=entry*(1+target_pct)
    si = np.flatnonzero(l <= stop); ti = np.flatnonzero(h >= target)
    sidx = int(si[0]) if len(si) else 10**9
    tidx = int(ti[0]) if len(ti) else 10**9
    if sidx <= tidx and sidx < 10**9:
        base = o[sidx] if o[sidx] <= stop else stop
        return (slip(base,"SELL",xb)-entry)/entry
    if tidx < 10**9:
        return (slip(target,"SELL",xb)-entry)/entry
    return (slip(c[-1],"SELL",xb)-entry)/entry


def trail_return(b, raw_entry, hard_stop, activation, trail_pct, hold=240, eb=25, xb=25):
    entry = slip(raw_entry,"BUY",eb)
    cutoff = b["entry_ts"] + pd.Timedelta(minutes=hold)
    prior_peak = entry
    used = False
    last_close = None
    for t,o,h,l,c in zip(b["ts"],b["open"],b["high"],b["low"],b["close"]):
        if pd.Timestamp(t) >= cutoff:
            break
        last_close = float(c)
        hs = entry*(1-hard_stop)
        if l <= hs:
            base = o if o <= hs else hs
            return (slip(base,"SELL",xb)-entry)/entry
        if prior_peak >= entry*(1+activation):
            used = True
            tr = prior_peak*(1-trail_pct)
            if l <= tr:
                base = o if o <= tr else tr
                return (slip(base,"SELL",xb)-entry)/entry
        prior_peak = max(prior_peak,float(h))
    if last_close is None:
        return np.nan
    return (slip(last_close,"SELL",xb)-entry)/entry


def main():
    block_http()
    prior = Path("data/offline_prior_artifact")
    matches = list(prior.glob("**/ignitions_first.csv"))
    if not matches: raise RuntimeError("missing retained ignition artifact")
    ig = pd.read_csv(matches[0])
    ig = ig[(ig.population=="BOTH") & ig.ignition_window.isin(["10:30-15:00","15:00-16:00","16:00-20:00"])].copy()
    cache = Path("data/cache/serclick_alpaca/minute")
    event_bars = {}
    for r in ig.itertuples(index=False):
        event_bars[(r.date,r.symbol)] = load_event_bars(cache,r)
    variants = {
        "POST1030": ig.index,
        "MIDDAY": ig.index[ig.ignition_window.eq("10:30-15:00")],
    }
    rules=[]
    for s in (0.07,0.10,0.15,0.20):
        for t in (0.40,0.50,0.75,1.00):
            for h in (120,240):
                rules.append(("TARGET",f"S{int(s*100):02d}_T{int(t*100):02d}_H{h}",(s,t,h)))
    for s in (0.10,0.15):
        for a in (0.15,0.20,0.30):
            for tr in (0.05,0.10,0.15):
                rules.append(("TRAIL",f"S{int(s*100):02d}_A{int(a*100):02d}_TR{int(tr*100):02d}_H240",(s,a,tr)))
    rows=[]
    for v,idxs in variants.items():
        for fam,rid,args in rules:
            by_split={"development":[],"validation":[],"test":[]}
            for i in idxs:
                r=ig.loc[i]; b=event_bars.get((r.date,r.symbol))
                if b is None: continue
                ret = target_return(b,float(r.entry_raw_open),*args) if fam=="TARGET" else trail_return(b,float(r.entry_raw_open),*args)
                by_split[r.split].append(ret)
            rec={"variant":v,"family":fam,"rule_id":rid}
            for sp,vals in by_split.items():
                m=metric(vals)
                for k,val in m.items(): rec[f"{sp}_{k}"]=val
            rec["exp_floor"]=min(rec["development_expectancy"],rec["validation_expectancy"])
            rec["pf_floor"]=min(rec["development_pf"],rec["validation_pf"])
            rec["qualifies"]=(rec["development_n"]>=15 and rec["validation_n"]>=8 and rec["development_expectancy"]>=0.10 and rec["validation_expectancy"]>=0.10 and rec["development_pf"]>=1.5 and rec["validation_pf"]>=1.5)
            rows.append(rec)
    out=pd.DataFrame(rows).sort_values(["qualifies","exp_floor","pf_floor"],ascending=[False,False,False])
    print("FAST_EXPLOSIVE_DEV_VAL_TOP20")
    print(out.drop(columns=[c for c in out.columns if c.startswith("test_")]).head(20).to_string(index=False))
    q=out[out.qualifies]
    print("FAST_EXPLOSIVE_10PCT_QUALIFIERS",len(q))
    if not q.empty:
        print("FAST_EXPLOSIVE_LOCKED_TEST_REVEAL")
        print(q.head(20).to_string(index=False))
    else:
        print("NO_BASE_RULE_CLEARED_10PCT_DEV_AND_VALIDATION")

if __name__=="__main__": main()
