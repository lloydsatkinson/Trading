from __future__ import annotations
from dataclasses import dataclass, asdict
import math
import numpy as np
import pandas as pd

NY='America/New_York'

@dataclass(frozen=True)
class Signal:
    strategy:str; side:str; ticker:str; session_date:str; signal_ts:str; i:int; stop:float; hold:int=60

@dataclass(frozen=True)
class Trade:
    strategy:str; side:str; ticker:str; session_date:str; signal_ts:str; entry_ts:str; exit_ts:str
    entry:float; exit:float; stop:float; target:float; r:float; reason:str


def prep(df:pd.DataFrame)->pd.DataFrame:
    req={'timestamp','open','high','low','close','volume','previous_close'}
    miss=req-set(df.columns)
    if miss: raise ValueError(f'missing {sorted(miss)}')
    x=df.copy(); x['timestamp']=pd.to_datetime(x['timestamp'],utc=True,errors='coerce')
    x=x.dropna(subset=['timestamp']).sort_values('timestamp').drop_duplicates('timestamp').reset_index(drop=True)
    for c in ['open','high','low','close','volume','previous_close']: x[c]=pd.to_numeric(x[c],errors='coerce')
    x=x.dropna(subset=['open','high','low','close','previous_close'])
    z=x['timestamp'].dt.tz_convert(NY); x['m']=z.dt.hour*60+z.dt.minute; x['session_date']=z.dt.date.astype(str)
    if 'ticker' not in x:x['ticker']='UNKNOWN'
    reg=(x.m>=570)&(x.m<960); typ=(x.high+x.low+x.close)/3; vv=x.volume.fillna(0).where(reg,0)
    x['vwap']=((typ*x.volume.fillna(0)).where(reg,0).cumsum()/vv.cumsum().replace(0,np.nan)).ffill()
    x['cum_volume']=vv.cumsum(); x['hod']=x.high.where(reg).cummax(); x['all_hi']=x.high.cummax()
    x['gain_hi']=x.hod/x.previous_close-1; x['gain_all']=x.all_hi/x.previous_close-1
    x['dd_hod']=1-x.close/x.hod; x['dd_all']=1-x.close/x.all_hi
    x['vmed']=x.volume.rolling(10,min_periods=3).median().shift(1)
    return x

def cross_up(x,i): return i>0 and pd.notna(x.vwap.iloc[i]) and x.close.iloc[i]>x.vwap.iloc[i] and x.close.iloc[i-1]<=x.vwap.iloc[i-1]
def cross_dn(x,i): return i>0 and pd.notna(x.vwap.iloc[i]) and x.close.iloc[i]<x.vwap.iloc[i] and x.close.iloc[i-1]>=x.vwap.iloc[i-1]
def volexp(x,i,k=1.4): return pd.notna(x.vmed.iloc[i]) and x.vmed.iloc[i]>0 and x.volume.iloc[i]>=k*x.vmed.iloc[i]
def higher_low(x,i): return i>=8 and x.low.iloc[i-2:i+1].min()>x.low.iloc[i-8:i-2].min()*1.005
def lower_high(x,i): return i>=8 and x.high.iloc[i-2:i+1].max()<x.high.iloc[i-8:i-2].max()*0.995

def sig(x,i,name,side,stop,hold=60):
    px=float(x.close.iloc[i]); stop=float(stop); risk=px-stop if side=='LONG' else stop-px
    if not (px>0 and stop>0 and 0<risk<=px*.15): return None
    return Signal(name,side,str(x.ticker.iloc[i]).upper(),str(x.session_date.iloc[i]),x.timestamp.iloc[i].isoformat(),int(i),stop,hold)

def detect(x:pd.DataFrame)->list[Signal]:
    out=[]
    reg=x[(x.m>=570)&(x.m<960)]; hits=reg.index[reg.low<=reg.previous_close*.90].tolist()
    if hits:
        t=int(hits[0])
        for i in range(t+5,len(x)):
            if x.m.iloc[i]>930: break
            pl=float(x.low.iloc[t:i+1].min())
            if cross_up(x,i) and higher_low(x,i) and volexp(x,i,1.4) and x.close.iloc[i]>=pl*1.05:
                s=sig(x,i,'SSR_FLUSH_RECLAIM','LONG',pl*.995,45)
                if s: out.append(s); break
    if 'ssr_next_day' in x and bool(x.ssr_next_day.iloc[0]):
        ro=x[x.m>=570]
        if not ro.empty:
            op=float(ro.open.iloc[0])
            for i in range(8,len(x)):
                if not 575<=x.m.iloc[i]<=750: continue
                weak=op<=x.previous_close.iloc[i]*1.02 or x.low.iloc[:i+1].min()<=x.previous_close.iloc[i]*.95
                if weak and cross_up(x,i) and higher_low(x,i) and volexp(x,i,1.25):
                    s=sig(x,i,'SSR_DAY2_RECLAIM','LONG',x.low.iloc[max(0,i-10):i+1].min(),60)
                    if s: out.append(s); break
    for i in range(12,len(x)):
        if 585<=x.m.iloc[i]<=930 and x.gain_all.iloc[i]>=.25 and x.dd_all.iloc[i]>=.12 and cross_up(x,i) and higher_low(x,i) and volexp(x,i):
            s=sig(x,i,'RUNNER_VWAP_RECLAIM','LONG',x.low.iloc[i-7:i+1].min(),45)
            if s: out.append(s); break
    for i in range(30,len(x)):
        if not 600<=x.m.iloc[i]<=900: continue
        prev=float(x.previous_close.iloc[i]); ih=float(x.high.iloc[:i-20].max())
        if ih<prev*1.15: continue
        b=x.iloc[i-20:i]; e=b.iloc[:10]; l=b.iloc[10:]
        er=(e.high.max()-e.low.min())/max(e.close.median(),1e-9); lr=(l.high.max()-l.low.min())/max(l.close.median(),1e-9)
        retain=(b.close.tail(5).median()-prev)/max(ih-prev,1e-9); ev=e.volume.median(); lv=l.volume.median(); pivot=b.high.max()
        if retain>=.65 and er>0 and lr<=er*.70 and ev>0 and lv<=ev*.65 and x.close.iloc[i]>pivot and x.volume.iloc[i]>=max(1,lv)*2:
            s=sig(x,i,'SBE_MIDDAY_EXPANSION','LONG',b.low.tail(10).min(),60)
            if s: out.append(s); break
    if 'prior20_max_volume' in x and pd.notna(x.prior20_max_volume.iloc[0]) and float(x.prior20_max_volume.iloc[0])>0:
        pmax=float(x.prior20_max_volume.iloc[0])
        for i in range(25,len(x)):
            if not 600<=x.m.iloc[i]<=930 or x.cum_volume.iloc[i]<pmax or x.gain_hi.iloc[i]<.15: continue
            b=x.iloc[i-20:i]; pivot=b.high.max(); width=(pivot-b.low.min())/max(b.close.median(),1e-9)
            if width<=.12 and x.close.iloc[i]>pivot and volexp(x,i,1.5):
                s=sig(x,i,'HIGHEST_VOLUME_DAY_BREAKOUT','LONG',b.low.tail(10).min(),60)
                if s: out.append(s); break
    morning=x[(x.m>=570)&(x.m<=720)]
    if not morning.empty:
        prev=float(x.previous_close.iloc[0]); mh=float(morning.high.max()); mv=max(1,float(morning.volume.median()))
        if mh>=prev*1.20:
            for i in range(35,len(x)):
                if not 810<=x.m.iloc[i]<=950: continue
                retain=(x.close.iloc[i]-prev)/max(mh-prev,1e-9); b=x.iloc[i-30:i]; pivot=b.high.max(); width=(pivot-b.low.min())/max(b.close.median(),1e-9)
                if retain>=.70 and x.close.iloc[i]>x.vwap.iloc[i] and width<=.10 and b.volume.median()<=mv*.70 and x.close.iloc[i]>pivot and volexp(x,i):
                    s=sig(x,i,'AFTERNOON_HOD_CONTINUATION','LONG',b.low.tail(10).min(),50)
                    if s: out.append(s); break
    for i in range(10,len(x)):
        if 575<=x.m.iloc[i]<=780 and x.gain_all.iloc[i]>=.30 and x.dd_all.iloc[i]>=.10 and cross_dn(x,i) and lower_high(x,i):
            s=sig(x,i,'POP_AND_DROP','SHORT',x.high.iloc[i-7:i+1].max()*1.003,60)
            if s: out.append(s); break
    for i in range(12,len(x)):
        if not 600<=x.m.iloc[i]<=900 or x.gain_all.iloc[i]<.25 or pd.isna(x.vwap.iloc[i]) or x.close.iloc[i]>=x.vwap.iloc[i]*.997: continue
        touch=x.high.iloc[i]>=x.vwap.iloc[i]*.995 and x.high.iloc[i]<=x.vwap.iloc[i]*1.015
        if touch and (x.close.iloc[i-5:i]<x.vwap.iloc[i-5:i]).sum()>=3 and x.close.iloc[i]<x.open.iloc[i]:
            s=sig(x,i,'BACKSIDE_VWAP_REJECTION','SHORT',x.high.iloc[i-5:i+1].max()*1.003,60)
            if s: out.append(s); break
    for i in range(10,len(x)):
        if not 585<=x.m.iloc[i]<=900: continue
        ph=x.high.iloc[:i].max(); prev=float(x.previous_close.iloc[i])
        if ph>=prev*1.25 and x.high.iloc[i]>ph*1.005 and x.close.iloc[i]<ph*.998 and volexp(x,i,1.3):
            s=sig(x,i,'FAILED_HOD_BREAK','SHORT',x.high.iloc[i]*1.005,45)
            if s: out.append(s); break
    for i in range(20,len(x)):
        if 870<=x.m.iloc[i]<=950 and x.gain_hi.iloc[i]>=.30:
            support=x.low.iloc[i-15:i].min()
            if x.close.iloc[i]<support and x.close.iloc[i]<x.vwap.iloc[i] and volexp(x,i):
                s=sig(x,i,'LATE_DAY_EXHAUSTION','SHORT',x.high.iloc[i-8:i+1].max()*1.003,60)
                if s: out.append(s); break
    return out

def simulate(df:pd.DataFrame,s:Signal,slip_bps=20,target_r=2.0)->Trade|None:
    x=prep(df); j=s.i+1
    if j>=len(x): return None
    q=slip_bps/10000; raw=float(x.open.iloc[j]); entry=raw*(1+q if s.side=='LONG' else 1-q)
    risk=entry-s.stop if s.side=='LONG' else s.stop-entry
    if risk<=0 or risk>entry*.20:return None
    target=entry+target_r*risk if s.side=='LONG' else entry-target_r*risk; last=min(len(x)-1,j+s.hold)
    ex=None; reason='TIME'; k=last
    for k0 in range(j,last+1):
        lo,hi=float(x.low.iloc[k0]),float(x.high.iloc[k0])
        if s.side=='LONG':
            if lo<=s.stop: ex=s.stop*(1-q); reason='STOP'; k=k0; break
            if hi>=target: ex=target*(1-q); reason='TARGET'; k=k0; break
        else:
            if hi>=s.stop: ex=s.stop*(1+q); reason='STOP'; k=k0; break
            if lo<=target: ex=target*(1+q); reason='TARGET'; k=k0; break
    if ex is None:
        raw=float(x.close.iloc[last]); ex=raw*(1-q if s.side=='LONG' else 1+q)
    r=(ex-entry)/risk if s.side=='LONG' else (entry-ex)/risk
    return Trade(s.strategy,s.side,s.ticker,s.session_date,s.signal_ts,x.timestamp.iloc[j].isoformat(),x.timestamp.iloc[k].isoformat(),entry,float(ex),s.stop,target,float(r),reason)

def run_day(df:pd.DataFrame,slip_bps=20)->list[Trade]:
    x=prep(df); return [t for s in detect(x) if (t:=simulate(df,s,slip_bps))]

def metrics(trades:pd.DataFrame,sessions:int)->pd.DataFrame:
    cols=['strategy','side','n','trades_per_day','profit_factor','expectancy_r','win_rate','max_drawdown_r']
    if trades.empty:return pd.DataFrame(columns=cols)
    out=[]
    for (st,side),g in trades.groupby(['strategy','side']):
        if 'entry_ts' in g:g=g.sort_values('entry_ts')
        v=pd.to_numeric(g.r,errors='coerce').dropna(); pos=v[v>0].sum(); neg=-v[v<0].sum(); pf=pos/neg if neg>0 else (math.inf if pos>0 else 0)
        eq=pd.Series([0.0]+v.cumsum().tolist()); dd=(eq.cummax()-eq).max()
        out.append([st,side,len(v),len(v)/max(1,sessions),float(pf),float(v.mean()),float((v>0).mean()),float(dd)])
    return pd.DataFrame(out,columns=cols)
