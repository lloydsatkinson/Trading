from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd

from scanner.core.replay import ReplayRule, apply_entry_slippage, simulate_trade
from scanner.core.features import prepare_intraday_bars
from scanner.core.validation import chronological_split
from scanner.multistrategy.config import MultiStrategyConfig
from scanner.multistrategy.study import broad_candidate_context
from scanner.strategies.orb_stocks_in_play.strategy import generate_orb_signals
from scanner.strategies.vwap_momentum.strategy import generate_vwap_signals
from scripts.run_offline_cached_replay import _block_http, _read_bars, _daily_prior_close, _opening30_rvol_map


def _pf(values: pd.Series) -> float:
    x = pd.to_numeric(values, errors='coerce').dropna()
    pos = float(x[x > 0].sum())
    neg = float(x[x < 0].sum())
    if neg == 0:
        return float('inf') if pos > 0 else 0.0
    return pos / abs(neg)


def main() -> None:
    _block_http()
    root = Path('.')
    cache = root / 'data' / 'cache' / 'serclick_alpaca'
    minute_files = sorted((cache / 'minute').glob('*_sip.csv.gz'))
    early_files = sorted((cache / 'early').glob('*_sip.csv.gz'))
    if not minute_files or not early_files:
        raise RuntimeError('missing restored cache')

    dates = sorted({p.name.split('_sip.csv.gz')[0] for p in early_files})
    cfg = MultiStrategyConfig()
    split_map = chronological_split([pd.Timestamp(d).date() for d in dates], cfg.development_sessions, cfg.validation_sessions, cfg.test_sessions)

    by_day: dict[str, set[str]] = {}
    union: set[str] = set()
    for path in minute_files:
        day = path.name.split('_sip.csv.gz')[0]
        x = _read_bars(path)
        syms = set(x['symbol'].astype(str)) if not x.empty else set()
        by_day[day] = syms
        union.update(syms)

    prior_close = _daily_prior_close(cache, union)
    rvol_map = _opening30_rvol_map(cache, union, cfg.opening_baseline_sessions)

    contexts: list[dict] = []
    for path in early_files:
        day = path.name.split('_sip.csv.gz')[0]
        day_syms = by_day.get(day, set())
        if not day_syms:
            continue
        x = _read_bars(path)
        x = x[x['symbol'].astype(str).isin(day_syms)]
        if x.empty:
            continue
        x = prepare_intraday_bars(x)
        d = pd.Timestamp(day).date()
        for symbol, g in x.groupby('symbol', sort=False):
            symbol = str(symbol)
            pc = prior_close.get((symbol, d))
            if pc is None:
                continue
            ctx = broad_candidate_context(g, pc, cfg)
            if not ctx.get('broad_candidate'):
                continue
            rv = rvol_map.get((symbol, day))
            if rv is None:
                continue
            rvol, history_n = rv
            ctx.update({
                'symbol': symbol,
                'date': day,
                'split': split_map[d],
                'feed': 'SIP',
                'market_cap': np.nan,
                'market_cap_bucket': 'UNKNOWN',
                'opening_rvol': float(rvol),
                'opening_rvol_proxy': 'OPENING30_VS_PRIOR20_OPENING30',
                'opening_rvol_history_n': int(history_n),
                'catalyst_class': 'UNKNOWN',
            })
            contexts.append(ctx)

    context_df = pd.DataFrame(contexts)
    print(f'SCOUT_CONTEXTS {len(context_df)}', flush=True)

    signal_frames: list[pd.DataFrame] = []
    iterable = context_df.groupby('date', sort=True) if not context_df.empty else []
    for day, group in iterable:
        minute = _read_bars(cache / 'minute' / f'{day}_sip.csv.gz')
        for ctx in group.to_dict('records'):
            bars = minute[minute['symbol'].astype(str).eq(str(ctx['symbol']))].copy()
            for gen in (generate_orb_signals, generate_vwap_signals):
                out = gen(bars, ctx)
                if not out.empty:
                    signal_frames.append(out)

    signals = pd.concat(signal_frames, ignore_index=True, sort=False) if signal_frames else pd.DataFrame()
    print('SCOUT_SIGNAL_COUNTS', flush=True)
    if signals.empty:
        print('NO_SIGNALS', flush=True)
        return
    print(signals.groupby(['strategy_id','variant_id','direction','split']).size().reset_index(name='n').to_string(index=False), flush=True)

    bars_by_day = {p.name.split('_sip.csv.gz')[0]: _read_bars(p) for p in minute_files}
    rows = []
    for sig in signals.to_dict('records'):
        day = str(sig['date'])
        daybars = bars_by_day.get(day, pd.DataFrame())
        sbars = daybars[daybars['symbol'].astype(str).eq(str(sig['symbol']))].copy()
        if sbars.empty:
            continue
        for bps in (25.0, 50.0, 100.0):
            entry = apply_entry_slippage(float(sig['entry_price_raw']), str(sig['direction']), bps)
            for hold in (15, 30, 60, 120):
                result = simulate_trade(sbars, entry, sig['entry_timestamp'], sig['direction'], ReplayRule(max_hold_minutes=hold), session_end='16:00')
                rows.append({
                    'strategy_id': sig['strategy_id'], 'variant_id': sig['variant_id'], 'direction': sig['direction'],
                    'symbol': sig['symbol'], 'date': day, 'split': sig['split'], 'slippage_bps': bps,
                    'hold_minutes': hold, 'return_pct': result.return_pct, 'mfe_pct': result.mfe_pct, 'mae_pct': result.mae_pct,
                })
    replay = pd.DataFrame(rows)
    agg_rows = []
    dims = ['strategy_id','variant_id','direction','split','slippage_bps','hold_minutes']
    for keys, g in replay.groupby(dims, dropna=False, sort=False):
        r = pd.to_numeric(g['return_pct'], errors='coerce').dropna()
        if r.empty:
            continue
        agg_rows.append({**dict(zip(dims, keys)), 'n': len(r), 'expectancy': float(r.mean()), 'median_return': float(r.median()), 'win_rate': float((r>0).mean()), 'profit_factor': _pf(r), 'mean_mfe': float(pd.to_numeric(g['mfe_pct'], errors='coerce').mean()), 'mean_mae': float(pd.to_numeric(g['mae_pct'], errors='coerce').mean())})
    summary = pd.DataFrame(agg_rows)

    print('SCOUT_VALIDATION_25BPS', flush=True)
    val = summary[(summary['split']=='validation') & (summary['slippage_bps']==25.0) & (summary['n']>=5)].copy()
    if val.empty:
        print('NO_VALIDATION_ROWS', flush=True)
    else:
        best = val.sort_values(['profit_factor','expectancy'], ascending=False).groupby(['strategy_id','variant_id','direction'], as_index=False).head(1)
        for _, row in best.iterrows():
            test = summary[(summary['strategy_id']==row['strategy_id']) & (summary['variant_id']==row['variant_id']) & (summary['direction']==row['direction']) & (summary['split']=='test') & (summary['slippage_bps']==25.0) & (summary['hold_minutes']==row['hold_minutes'])]
            test_pf = float(test.iloc[0]['profit_factor']) if len(test) else np.nan
            test_exp = float(test.iloc[0]['expectancy']) if len(test) else np.nan
            print(f"{row['strategy_id']} {row['variant_id']} {row['direction']} hold={int(row['hold_minutes'])} val_n={int(row['n'])} val_pf={row['profit_factor']:.3f} val_exp={row['expectancy']:.4f} val_wr={row['win_rate']:.3f} test_pf={test_pf:.3f} test_exp={test_exp:.4f}", flush=True)

    print('SCOUT_SLIPPAGE_60M', flush=True)
    x = summary[(summary['split'].isin(['validation','test'])) & (summary['hold_minutes']==60)].copy()
    if not x.empty:
        print(x[['strategy_id','variant_id','direction','split','slippage_bps','n','profit_factor','expectancy','win_rate']].sort_values(['strategy_id','variant_id','direction','split','slippage_bps']).to_string(index=False), flush=True)


if __name__ == '__main__':
    main()
