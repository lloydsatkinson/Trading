from pathlib import Path

research = Path("scanner/strategies/dan_irish/research.py")
text = research.read_text(encoding="utf-8")
old = '''    ensure_dan_followup_caches(study, contexts, daily_bars, cfg)
    frames: list[pd.DataFrame] = []
    skips: list[dict] = []
'''
new = '''    prepared_daily = (
        daily_bars.copy()
        if not daily_bars.empty and {"timestamp_et", "session_date"}.issubset(daily_bars.columns)
        else prepare_intraday_bars(daily_bars)
    )
    ensure_dan_followup_caches(study, contexts, prepared_daily, cfg)
    daily_by_symbol = (
        {
            str(symbol): group.copy()
            for symbol, group in prepared_daily.groupby(prepared_daily["symbol"].astype(str), sort=False)
        }
        if not prepared_daily.empty and "symbol" in prepared_daily.columns
        else {}
    )
    frames: list[pd.DataFrame] = []
    skips: list[dict] = []
'''
assert old in text
text = text.replace(old, new, 1)
old = '''        swing = generate_dan_swing_signals(
            context,
            daily_bars,
            load_symbol_minutes,
'''
new = '''        swing = generate_dan_swing_signals(
            context,
            daily_by_symbol.get(symbol, pd.DataFrame()),
            load_symbol_minutes,
'''
assert old in text
text = text.replace(old, new, 1)
research.write_text(text, encoding="utf-8")

swing = Path("scanner/strategies/dan_irish/swing.py")
text = swing.read_text(encoding="utf-8")
old = '''def _daily_frame(daily_bars: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if daily_bars.empty:
        return pd.DataFrame()
    x = prepare_intraday_bars(daily_bars)
    x = x[x["symbol"].astype(str).eq(str(symbol))].copy()
'''
new = '''def _daily_frame(daily_bars: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if daily_bars.empty:
        return pd.DataFrame()
    x = (
        daily_bars.copy()
        if {"timestamp_et", "session_date"}.issubset(daily_bars.columns)
        else prepare_intraday_bars(daily_bars)
    )
    x = x[x["symbol"].astype(str).eq(str(symbol))].copy()
'''
assert old in text
text = text.replace(old, new, 1)
swing.write_text(text, encoding="utf-8")
