import pandas as pd
from trading_lab.alpaca_intraday import coarse,common_assets
from trading_lab.intraday_v1 import Signal,simulate,metrics,prep


def bars(n=10):
    ts=pd.date_range('2026-07-21 13:30:00+00:00',periods=n,freq='min')
    return pd.DataFrame({'timestamp':ts,'ticker':'TEST','open':10.0,'high':10.1,'low':9.9,'close':10.0,'volume':10000,'previous_close':8.0})

def test_daily_coarse_is_permissive_for_pops_and_ssr():
    assert coarse(12,8,500000,10)
    assert coarse(10,8.9,500000,10)
    assert not coarse(10.2,9.9,500000,10)

def test_common_asset_filter_removes_etf_and_warrant():
    rows=[{'symbol':'ABC','class':'us_equity','exchange':'NASDAQ','name':'ABC Corp'},{'symbol':'ABCW','class':'us_equity','exchange':'NASDAQ','name':'ABC Warrant'},{'symbol':'ZZZ','class':'us_equity','exchange':'NYSE','name':'ZZZ ETF'}]
    assert [x['symbol'] for x in common_assets(rows)]==['ABC']

def test_long_same_bar_target_and_stop_is_stop_first():
    f=bars();f.loc[3,'low']=9;f.loc[3,'high']=13
    s=Signal('X','LONG','TEST','2026-07-21',f.loc[2,'timestamp'].isoformat(),2,9.5,10)
    t=simulate(f,s,slip_bps=0)
    assert t.reason=='STOP' and t.r==-1

def test_short_same_bar_target_and_stop_is_stop_first():
    f=bars();f.loc[3,'high']=11;f.loc[3,'low']=7
    s=Signal('X','SHORT','TEST','2026-07-21',f.loc[2,'timestamp'].isoformat(),2,10.5,10)
    t=simulate(f,s,slip_bps=0)
    assert t.reason=='STOP' and t.r==-1

def test_metrics_count_zero_session_days_in_denominator():
    t=pd.DataFrame({'strategy':['A']*4,'side':['LONG']*4,'r':[2,-1,2,-1],'entry_ts':['2026-01-01T10:00:00Z']*4})
    m=metrics(t,10).iloc[0]
    assert m.profit_factor==2 and m.expectancy_r==.5 and m.trades_per_day==.4 and m.max_drawdown_r==1

def test_prep_uses_regular_session_vwap():
    x=prep(bars())
    assert x.vwap.notna().all() and x.gain_hi.iloc[-1]>.20
