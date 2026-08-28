from __future__ import annotations
import argparse,json,os
from dataclasses import asdict
from datetime import date
from pathlib import Path
import pandas as pd
from trading_lab.alpaca_intraday import Alpaca,prepare
from trading_lab.intraday_v1 import run_day,metrics

BLOCKED=['CATALYST_FIRST_PULLBACK','DILUTION_OR_OFFERING_FADE']

def split_map(session_dates):
    ds=list(session_dates); n=len(ds); a=int(n*.60); b=int(n*.80)
    return {d:('development' if i<a else 'validation' if i<b else 'holdout') for i,d in enumerate(ds)}

def md_table(df,cols):
    if df.empty:return 'No results.'
    head='| '+' | '.join(cols)+' |\n| '+' | '.join(['---']*len(cols))+' |'; rows=[]
    for _,r in df.iterrows():
        vals=[]
        for c in cols:
            v=r[c]
            if isinstance(v,float):vals.append('∞' if v==float('inf') else f'{v:.3f}')
            else:vals.append(str(v))
        rows.append('| '+' | '.join(vals)+' |')
    return head+'\n'+'\n'.join(rows)

def evaluate(minute,session_count,slip):
    rows=[]
    for _,g in minute.groupby(['date','ticker'],sort=True):rows.extend(asdict(t) for t in run_day(g,slip_bps=slip))
    t=pd.DataFrame(rows);return t,metrics(t,session_count)

def main():
    p=argparse.ArgumentParser();p.add_argument('--days',type=int,default=60);p.add_argument('--end-date',default='2026-08-11');p.add_argument('--feed',default='sip');p.add_argument('--output',default='output/intraday_tournament');p.add_argument('--max-symbols',type=int);p.add_argument('--reuse-history',action='store_true');p.add_argument('--slip-bps',type=float,default=20)
    a=p.parse_args();out=Path(a.output);hist=out/'history';out.mkdir(parents=True,exist_ok=True);mp=hist/'minute_candidates.csv.gz';client=None
    if not(a.reuse_history and mp.exists()):
        client=Alpaca(os.getenv('APCA_API_KEY_ID',''),os.getenv('APCA_API_SECRET_KEY',''),a.feed);manifest=prepare(client,hist,a.days,date.fromisoformat(a.end_date),a.max_symbols)
    else:manifest=json.loads((hist/'manifest.json').read_text())
    minute=pd.read_csv(mp);dates=manifest.get('session_dates')
    if not dates:
        try:
            client=client or Alpaca(os.getenv('APCA_API_KEY_ID',''),os.getenv('APCA_API_SECRET_KEY',''),a.feed)
            dates=[str(r['date'])[:10] for r in client.calendar(date.fromisoformat(manifest['start']),date.fromisoformat(manifest['end']))]
        except Exception:dates=sorted(minute.date.astype(str).unique())
    session_count=int(manifest.get('sessions') or len(dates));sm=split_map(dates)
    normal,nm=evaluate(minute,session_count,a.slip_bps);stress,smx=evaluate(minute,session_count,a.slip_bps*2)
    if not normal.empty:normal['split']=normal.session_date.map(sm)
    normal.to_csv(out/'trades.csv',index=False);nm.to_csv(out/'metrics_normal.csv',index=False);smx.to_csv(out/'metrics_2x_cost.csv',index=False)
    table=nm.merge(smx[['strategy','side','profit_factor','expectancy_r']],on=['strategy','side'],how='outer',suffixes=('','_2x')).fillna(0)
    split_rows=[];denoms={'development':int(session_count*.60),'validation':int(session_count*.20)};denoms['holdout']=session_count-denoms['development']-denoms['validation']
    if not normal.empty:
        for sp in ['development','validation','holdout']:
            z=metrics(normal[normal['split']==sp],denoms[sp]);z.insert(0,'split',sp);split_rows.append(z)
    splits=pd.concat(split_rows,ignore_index=True) if split_rows else pd.DataFrame();splits.to_csv(out/'metrics_splits.csv',index=False)
    status=[]
    for _,r in table.iterrows():
        st=r.strategy;side=r.side;n=int(r.n);s='FAIL'
        if n<30:s='INCONCLUSIVE_SAMPLE'
        elif r.profit_factor>=1.30 and r.expectancy_r>0 and r.profit_factor_2x>1.05 and r.expectancy_r_2x>0:
            ss=splits[splits.strategy==st] if not splits.empty else pd.DataFrame();stable=len(ss)>=3 and (ss.expectancy_r>0).sum()>=2
            s='PASS_CANDIDATE' if n>=100 and stable and side=='LONG' else 'PROVISIONAL_PASS' if side=='LONG' else 'RESEARCH_ONLY_BORROW_UNVERIFIED'
        if side=='SHORT' and s not in {'FAIL','INCONCLUSIVE_SAMPLE'}:s='RESEARCH_ONLY_BORROW_UNVERIFIED'
        status.append(s)
    if len(table):table['status']=status
    for b in BLOCKED:
        side='SHORT' if b=='DILUTION_OR_OFFERING_FADE' else 'LONG';table=pd.concat([table,pd.DataFrame([{'strategy':b,'side':side,'n':0,'trades_per_day':0,'profit_factor':0,'expectancy_r':0,'win_rate':0,'max_drawdown_r':0,'profit_factor_2x':0,'expectancy_r_2x':0,'status':'DATA_BLOCKED_POINT_IN_TIME_CONTEXT'}])],ignore_index=True)
    table.to_csv(out/'leaderboard.csv',index=False);cols=['strategy','side','n','trades_per_day','profit_factor','profit_factor_2x','expectancy_r','win_rate','max_drawdown_r','status']
    text=['# Intraday Small-Cap Tournament','',f"Sessions: {session_count} | {manifest.get('start')} to {manifest.get('end')} | Feed: {manifest.get('feed')} | Slippage: {a.slip_bps:.0f} bps/side; stress {a.slip_bps*2:.0f} bps/side",'',md_table(table[cols],cols),'','Short PF is theoretical until point-in-time borrow/locate availability and fees are joined. Catalyst/dilution models remain blocked rather than backfilled with present-day context.']
    (out/'summary.md').write_text('\n'.join(text));print('\n'.join(text))

if __name__=='__main__':main()
