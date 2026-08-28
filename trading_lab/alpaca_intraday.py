from __future__ import annotations
from collections import defaultdict
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import json,re,time
import pandas as pd
import requests

NY=ZoneInfo('America/New_York'); DATA='https://data.alpaca.markets'; TRADE='https://paper-api.alpaca.markets'
EXCH={'NASDAQ','NYSE','AMEX'}; NONCOMMON=(' WARRANT','WARRANT ',' RIGHTS',' UNITS',' UNIT ',' PREFERRED',' PFD',' ETF',' ETN','EXCHANGE TRADED FUND')

def common_assets(rows):
    out=[]; seen=set()
    for a in rows:
        s=str(a.get('symbol') or '').upper(); n=' '+str(a.get('name') or '').upper()+' '; ex=str(a.get('exchange') or '').upper(); cl=str(a.get('class') or a.get('asset_class') or '').lower()
        if not s or s in seen or cl!='us_equity' or ex not in EXCH or not s[0].isalpha() or '_' in s or any(t in n for t in NONCOMMON): continue
        seen.add(s); out.append(a)
    return sorted(out,key=lambda a:str(a.get('symbol') or ''))

def coarse(high,low,vol,prev):
    if prev<=0 or high<=0 or low<=0 or vol<250000 or high<.75 or low>25:return False
    return high/prev-1>=.05 or low/prev-1<=-.10 or high/max(low,1e-9)-1>=.15

def f(r,k,long,d=0):
    try:return float(r.get(k,r.get(long,d)) or d)
    except:return float(d)

def dayof(r):
    t=r.get('t') or r.get('timestamp'); z=pd.Timestamp(t)
    if z.tzinfo is None:z=z.tz_localize('UTC')
    return z.tz_convert(NY).date()

def et(d,h,m=0):return datetime(d.year,d.month,d.day,h,m,tzinfo=NY).astimezone(timezone.utc)
def chunks(xs,n):
    for i in range(0,len(xs),n):yield xs[i:i+n]

class Alpaca:
    def __init__(self,key,secret,feed='sip'):
        if not key or not secret:raise ValueError('APCA_API_KEY_ID/APCA_API_SECRET_KEY required')
        self.feed=feed; self.s=requests.Session(); self.s.headers.update({'APCA-API-KEY-ID':key,'APCA-API-SECRET-KEY':secret})
    def get(self,url,params=None):
        err=None
        for a in range(6):
            try:
                r=self.s.get(url,params=params,timeout=45)
                if r.status_code==429:time.sleep(float(r.headers.get('Retry-After') or min(8,1+a*1.5)));continue
                if 500<=r.status_code<600:time.sleep(min(8,1+a*1.5));continue
                r.raise_for_status();return r.json()
            except requests.HTTPError as e:
                if e.response is not None and 400<=e.response.status_code<500:raise
                err=e
            except (requests.RequestException,ValueError) as e:err=e
            if a<5:time.sleep(min(8,1+a*1.5))
        raise RuntimeError(err)
    def assets(self):
        out=[]
        for status in ('active','inactive'):
            try:out.extend(self.get(f'{TRADE}/v2/assets',{'asset_class':'us_equity','status':status}) or [])
            except requests.HTTPError:
                if status=='active':raise
        return out
    def calendar(self,start,end):return self.get(f'{TRADE}/v2/calendar',{'start':start.isoformat(),'end':end.isoformat()}) or []
    def bars(self,symbols,timeframe,start,end,asof=None):
        syms=[symbols] if isinstance(symbols,str) else list(symbols); out=defaultdict(list); page=None
        p={'symbols':','.join(syms),'timeframe':timeframe,'start':start.isoformat() if isinstance(start,datetime) else str(start),'end':end.isoformat() if isinstance(end,datetime) else str(end),'limit':10000,'adjustment':'split','feed':self.feed,'sort':'asc'}
        if asof:p['asof']=asof
        while syms:
            p['symbols']=','.join(syms)
            if page:p['page_token']=page
            else:p.pop('page_token',None)
            try:q=self.get(f'{DATA}/v2/stocks/bars',p)
            except requests.HTTPError as e:
                msg=''
                if e.response is not None:
                    try:msg=str((e.response.json() or {}).get('message') or '')
                    except:msg=e.response.text or ''
                m=re.search(r'invalid symbol:\s*([^\s,]+)',msg,re.I); bad=m.group(1).strip("'\"") if m else None
                if e.response is not None and e.response.status_code==400 and bad in syms:
                    syms=[s for s in syms if s!=bad];out=defaultdict(list);page=None;continue
                raise
            for s,rows in (q.get('bars') or {}).items():out[str(s).upper()].extend(rows or [])
            page=q.get('next_page_token')
            if not page:break
        return dict(out)

def daily_context(daily,sessions):
    out={}
    for s,rows in daily.items():
        by={dayof(r):r for r in rows}; closes=[]; vols=[]
        for d in sessions:
            r=by.get(d)
            if r is None:continue
            c,h,l,v=f(r,'c','close'),f(r,'h','high'),f(r,'l','low'),f(r,'v','volume'); prev=closes[-1] if closes else None
            p20=max(vols[-20:]) if vols else None
            p4=(prev/closes[-4]-1) if prev and len(closes)>=4 and closes[-4]>0 else None
            out[(s,d)]={'previous_close':prev,'high':h,'low':l,'volume':v,'close':c,'prior20_max_volume':p20,'prior4d_return':p4}
            if c>0:closes.append(c)
            if v>=0:vols.append(v)
    return out

def prepare(client,output,days=60,end_date=date(2026,8,11),max_symbols=None):
    out=Path(output);out.mkdir(parents=True,exist_ok=True)
    cal=client.calendar(end_date-timedelta(days=(days+35)*3),end_date); sessions=sorted({date.fromisoformat(str(r['date'])[:10]) for r in cal if date.fromisoformat(str(r['date'])[:10])<=end_date})
    if len(sessions)<days+22:raise RuntimeError('not enough sessions')
    evals=sessions[-days:]; context=sessions[-(days+22):]; assets=common_assets(client.assets())
    if max_symbols:assets=assets[:max_symbols]
    syms=[str(a['symbol']).upper() for a in assets];pd.DataFrame(assets).to_csv(out/'universe.csv',index=False)
    print(f'universe={len(syms):,} sessions={evals[0]}..{evals[-1]} feed={client.feed}')
    daily=defaultdict(list)
    for n,b in enumerate(chunks(syms,400),1):
        q=client.bars(b,'1Day',et(context[0],0),et(evals[-1],0)+timedelta(days=1),evals[-1].isoformat())
        for s,rows in q.items():daily[s].extend(rows)
        print('daily batch',n,len(b))
    ctx=daily_context(daily,context); cand=defaultdict(list); ssr=set()
    for d in evals:
        for s in syms:
            c=ctx.get((s,d))
            if not c or not c['previous_close']:continue
            if coarse(c['high'],c['low'],c['volume'],c['previous_close']):cand[d].append(s)
            if c['low']<=c['previous_close']*.90:ssr.add((s,d))
    ix={d:i for i,d in enumerate(context)}
    for s,d in list(ssr):
        j=ix[d]
        if j+1<len(context) and context[j+1] in evals:cand[context[j+1]].append(s)
    rows=[];coarse_rows=[]
    for no,d in enumerate(evals,1):
        names=sorted(set(cand[d]));print(f'minute {no:03d}/{len(evals)} {d} candidates={len(names)}')
        for s in names:coarse_rows.append({'date':d.isoformat(),'ticker':s,**ctx[(s,d)]})
        for b in chunks(names,80):
            q=client.bars(b,'1Min',et(d,4),et(d,16,1),d.isoformat())
            for s,bs in q.items():
                c=ctx[(s,d)];j=ix[d];prevd=context[j-1] if j>0 else None;day2=bool(prevd and (s,prevd) in ssr)
                for r in bs:
                    t=r.get('t') or r.get('timestamp')
                    if not t:continue
                    rows.append({'date':d.isoformat(),'ticker':s,'timestamp':t,'open':f(r,'o','open'),'high':f(r,'h','high'),'low':f(r,'l','low'),'close':f(r,'c','close'),'volume':f(r,'v','volume'),'previous_close':c['previous_close'],'prior20_max_volume':c['prior20_max_volume'],'prior4d_return':c['prior4d_return'],'ssr_next_day':day2})
    pd.DataFrame(coarse_rows).to_csv(out/'coarse_candidates.csv',index=False); minute=pd.DataFrame(rows);minute.to_csv(out/'minute_candidates.csv.gz',index=False,compression='gzip')
    m={'feed':client.feed,'sessions':len(evals),'start':evals[0].isoformat(),'end':evals[-1].isoformat(),'universe':len(syms),'candidate_days':len(coarse_rows),'minute_rows':len(minute),'limitations':['Daily H/L/V only select a permissive minute-download superset; they never create entries.','No historical NBBO: next-minute open plus modeled slippage is used.','Short borrow/locate is not verified; short results are theoretical until borrow data is joined.','Catalyst/dilution strategies are not scored in this bar-only pass.']}
    (out/'manifest.json').write_text(json.dumps(m,indent=2));return m
