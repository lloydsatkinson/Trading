"""Historical research spike only: LEO BOTH qualification at 10:00, next executable 10:01 entry.
Uses retained candidate outputs + restored minute cache. No market-data API calls or orders.
"""
from __future__ import annotations
from pathlib import Path
import math
import requests
import numpy as np
import pandas as pd

ET="America/New_York"


def block_http():
    def blocked(*args, **kwargs):
        raise RuntimeError("HTTP_DISABLED_OFFLINE_LEO_1000")
    requests.sessions.Session.request=blocked


def slip(price, side, bps=25):
    return float(price)*(1+bps/10000.0 if side=="BUY" else 1-bps/10000.0)


def metric(vals):
    s=pd.Series(vals,dtype=float).dropna()
    if s.empty: return dict(n=0,expectancy=np.nan,pf=np.nan,win_rate=np.nan,median=np.nan)
    gp=float(s[s>0].sum()); gl=float(-s[s<0].sum())
    pf=math.inf if gl==0 and gp>0 else (gp/gl if gl>0 else np.nan)
    return dict(n=len(s),expectancy=float(s.mean()),pf=float(pf),win_rate=float((s>0).mean()),median=float(s.median()))


def load_day(cache:Path, day:str):
    p=cache/f"{day}_sip.csv.gz"
    if not p.exists(): return pd.DataFrame()
    x=pd.read_csv(p)
    if x.empty: return x
    x["timestamp"]=pd.to_datetime(x.timestamp,utc=True,errors="coerce")
    x["timestamp_et"]=x.timestamp.dt.tz_convert(ET)
    return x


def event_arrays(daybars,symbol,day):
    x=daybars[daybars.symbol.astype(str).eq(str(symbol))].copy()
    if x.empty: return None
    start=pd.Timestamp(f"{day} 10:01:00",tz=ET)
    end=pd.Timestamp(f"{day} 20:00:00",tz=ET)
    x=x[(x.timestamp_et>=start)&(x.timestamp_et<end)].sort_values("timestamp_et")
    if x.empty:return None
    return {
        "ts":list(x.timestamp_et),
        "open":x.open.astype(float).to_numpy(),"high":x.high.astype(float).to_numpy(),
        "low":x.low.astype(float).to_numpy(),"close":x.close.astype(float).to_numpy(),
        "entry_ts":x.iloc[0].timestamp_et,"raw_entry":float(x.iloc[0].open)
    }


def cap_index(b, hold):
    if hold=="EOD16": cutoff=b["entry_ts"].normalize()+pd.Timedelta(hours=16)
    elif hold=="EOD20": cutoff=b["entry_ts"].normalize()+pd.Timedelta(hours=20)
    else: cutoff=b["entry_ts"]+pd.Timedelta(minutes=int(hold))
    n=0
    for t in b["ts"]:
        if t>=cutoff:break
        n+=1
    return max(1,min(n,len(b["close"])))


def target_return(b,stop_pct,target_pct,hold,eb=25,xb=25):
    entry=slip(b["raw_entry"],"BUY",eb); n=cap_index(b,hold)
    o,h,l,c=(b[k][:n] for k in ("open","high","low","close"))
    stop=entry*(1-stop_pct); target=entry*(1+target_pct)
    si=np.flatnonzero(l<=stop); ti=np.flatnonzero(h>=target)
    sidx=int(si[0]) if len(si) else 10**9; tidx=int(ti[0]) if len(ti) else 10**9
    if sidx<=tidx and sidx<10**9:
        base=o[sidx] if o[sidx]<=stop else stop
        return (slip(base,"SELL",xb)-entry)/entry
    if tidx<10**9:
        return (slip(target,"SELL",xb)-entry)/entry
    return (slip(c[-1],"SELL",xb)-entry)/entry


def trail_return(b,hard_stop,activation,trail_pct,hold="EOD16",eb=25,xb=25):
    entry=slip(b["raw_entry"],"BUY",eb); n=cap_index(b,hold)
    prior_peak=entry
    for o,h,l,c in zip(b["open"][:n],b["high"][:n],b["low"][:n],b["close"][:n]):
        hs=entry*(1-hard_stop)
        if l<=hs:
            base=o if o<=hs else hs
            return (slip(base,"SELL",xb)-entry)/entry
        if prior_peak>=entry*(1+activation):
            tr=prior_peak*(1-trail_pct)
            if l<=tr:
                base=o if o<=tr else tr
                return (slip(base,"SELL",xb)-entry)/entry
        prior_peak=max(prior_peak,float(h))
    return (slip(b["close"][n-1],"SELL",xb)-entry)/entry


def main():
    block_http()
    prior=Path("data/offline_prior_artifact")
    matches=list(prior.glob("**/candidates.csv"))
    if not matches: raise RuntimeError("missing retained candidates.csv")
    c=pd.read_csv(matches[0])
    c=c[c.population.eq("BOTH")].copy()
    # Predeclared filters, all knowable by 10:00. Test remains hidden unless a rule clears dev+validation.
    filters={
        "BOTH_ALL":lambda d:pd.Series(True,index=d.index),
        "HOD_EXT_GE_1_30":lambda d:pd.to_numeric(d.hod_1000_extension,errors="coerce")>=1.30,
        "HOD_EXT_GE_1_40":lambda d:pd.to_numeric(d.hod_1000_extension,errors="coerce")>=1.40,
        "PM_EXT_GE_1_30":lambda d:pd.to_numeric(d.pm_extension,errors="coerce")>=1.30,
        "PM_EXT_GE_1_50":lambda d:pd.to_numeric(d.pm_extension,errors="coerce")>=1.50,
        "OPEN30_DV_GE_10M":lambda d:pd.to_numeric(d.open30_dollar_turnover,errors="coerce")>=10_000_000,
        "OPEN30_DV_GE_20M":lambda d:pd.to_numeric(d.open30_dollar_turnover,errors="coerce")>=20_000_000,
        "OPEN30_DV_GE_50M":lambda d:pd.to_numeric(d.open30_dollar_turnover,errors="coerce")>=50_000_000,
        "FRESH_NOT_PRIOR_EXTREME":lambda d:~d.prior_1_5_extreme_runner.fillna(False).astype(bool),
        "HOD130_AND_DV10M":lambda d:(pd.to_numeric(d.hod_1000_extension,errors="coerce")>=1.30)&(pd.to_numeric(d.open30_dollar_turnover,errors="coerce")>=10_000_000),
    }
    cache=Path("data/cache/serclick_alpaca/minute")
    arr={}
    for day,g in c.groupby("date",sort=True):
        db=load_day(cache,str(day))
        if db.empty: continue
        for r in g.itertuples(index=False):
            arr[(str(r.date),str(r.symbol))]=event_arrays(db,r.symbol,r.date)
    rules=[]
    for s in (0.05,0.07,0.10,0.15,0.20,0.30):
        for t in (0.10,0.20,0.30,0.40,0.50,0.75,1.00):
            for h in (60,120,240,"EOD16","EOD20"):
                rules.append(("TARGET",f"S{int(s*100):02d}_T{int(t*100):02d}_{h}",(s,t,h)))
    for s in (0.07,0.10,0.15,0.20):
        for a in (0.10,0.15,0.20,0.30):
            for tr in (0.05,0.10,0.15):
                for h in (120,240,"EOD16"):
                    rules.append(("TRAIL",f"S{int(s*100):02d}_A{int(a*100):02d}_TR{int(tr*100):02d}_{h}",(s,a,tr,h)))
    # Simulate every candidate/rule once at baseline costs.
    sim=[]
    for r in c.itertuples(index=False):
        b=arr.get((str(r.date),str(r.symbol)))
        if b is None: continue
        for fam,rid,args in rules:
            ret=target_return(b,*args) if fam=="TARGET" else trail_return(b,*args)
            sim.append({"date":r.date,"symbol":r.symbol,"split":r.split,"family":fam,"rule_id":rid,"return_pct":ret})
    sim=pd.DataFrame(sim)
    print("LEO1000_CANDIDATES",len(c),"CACHED",len(arr),"SIM_ROWS",len(sim))
    ranked=[]
    for fname,ffn in filters.items():
        selected=c[ffn(c).fillna(False)][["date","symbol","split"]]
        x=sim.merge(selected,on=["date","symbol","split"],how="inner")
        for (fam,rid),g in x.groupby(["family","rule_id"],sort=False):
            rec={"filter":fname,"family":fam,"rule_id":rid}
            for sp in ("development","validation","test"):
                m=metric(g.loc[g.split.eq(sp),"return_pct"])
                for k,v in m.items():rec[f"{sp}_{k}"]=v
            rec["exp_floor"]=min(rec["development_expectancy"],rec["validation_expectancy"])
            rec["pf_floor"]=min(rec["development_pf"],rec["validation_pf"])
            rec["qualifies"]=(rec["development_n"]>=30 and rec["validation_n"]>=15 and rec["development_expectancy"]>=0.10 and rec["validation_expectancy"]>=0.10 and rec["development_pf"]>=1.5 and rec["validation_pf"]>=1.5)
            ranked.append(rec)
    out=pd.DataFrame(ranked).sort_values(["qualifies","exp_floor","pf_floor"],ascending=[False,False,False])
    print("LEO1000_DEV_VAL_TOP25")
    print(out.drop(columns=[c for c in out.columns if c.startswith("test_")]).head(25).to_string(index=False))
    q=out[out.qualifies].copy()
    print("LEO1000_10PCT_QUALIFIERS",len(q))
    if not q.empty:
        print("LEO1000_LOCKED_TEST_REVEAL")
        print(q.head(25).to_string(index=False))
    else:
        print("NO_LEO1000_RULE_CLEARED_10PCT_DEV_AND_VALIDATION")

if __name__=="__main__":main()
