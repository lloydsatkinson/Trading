from pathlib import Path

research = Path("scanner/strategies/dan_irish/research.py")
text = research.read_text(encoding="utf-8")

old = "from __future__ import annotations\n\nfrom datetime import date\n"
new = "from __future__ import annotations\n\nfrom collections import OrderedDict\nfrom datetime import date\n"
assert old in text
text = text.replace(old, new, 1)

old = '''MinuteCacheLoader = Callable[[Path, str, str, str, str], pd.DataFrame]\n\n\ndef run_study_with_optional_dan'''
new = '''MinuteCacheLoader = Callable[[Path, str, str, str, str], pd.DataFrame]\nDayMinuteLoader = Callable[[Path, str, str, str], pd.DataFrame]\n\n\ndef make_cached_symbol_minute_loader(\n    day_loader: DayMinuteLoader,\n    max_days: int = 24,\n) -> MinuteCacheLoader:\n    \"\"\"Bound full-day minute decompression to once per recently used cache key.\"\"\"\n    limit = int(max_days)\n    if limit <= 0:\n        raise ValueError(\"max_days must be positive\")\n    cache: OrderedDict[tuple[str, str, str, str], dict[str, pd.DataFrame]] = OrderedDict()\n\n    def load(root: Path, namespace: str, day: str, feed: str, symbol: str) -> pd.DataFrame:\n        key = (str(Path(root)), str(namespace), str(day), str(feed).lower())\n        if key in cache:\n            by_symbol = cache.pop(key)\n            cache[key] = by_symbol\n        else:\n            frame = day_loader(Path(root), str(namespace), str(day), str(feed))\n            by_symbol: dict[str, pd.DataFrame] = {}\n            if frame is not None and not frame.empty and \"symbol\" in frame.columns:\n                symbols = frame[\"symbol\"].astype(str)\n                for value in symbols.unique():\n                    by_symbol[str(value)] = frame.loc[symbols.eq(str(value))].copy()\n            cache[key] = by_symbol\n            while len(cache) > limit:\n                cache.popitem(last=False)\n        selected = by_symbol.get(str(symbol))\n        return selected.copy() if selected is not None else pd.DataFrame()\n\n    return load\n\n\ndef run_study_with_optional_dan'''
assert old in text
text = text.replace(old, new, 1)

old = '''def _daily_dates_for_symbol(daily_bars: pd.DataFrame, symbol: str) -> list[date]:\n    if daily_bars.empty:\n        return []\n    x = prepare_intraday_bars(daily_bars)\n    x = x[x[\"symbol\"].astype(str).eq(str(symbol))]\n    return sorted(set(x[\"session_date\"].tolist()))\n'''
new = '''def _daily_dates_by_symbol(daily_bars: pd.DataFrame) -> dict[str, list[date]]:\n    if daily_bars.empty:\n        return {}\n    x = prepare_intraday_bars(daily_bars)\n    if x.empty or \"symbol\" not in x.columns:\n        return {}\n    return {\n        str(symbol): sorted(set(group[\"session_date\"].tolist()))\n        for symbol, group in x.groupby(x[\"symbol\"].astype(str), sort=False)\n    }\n\n\ndef _daily_dates_for_symbol(daily_bars: pd.DataFrame, symbol: str) -> list[date]:\n    return _daily_dates_by_symbol(daily_bars).get(str(symbol), [])\n'''
assert old in text
text = text.replace(old, new, 1)

old = '''    symbols_by_day: dict[date, set[str]] = {}\n    for context in contexts.to_dict(\"records\"):\n        symbol = str(context[\"symbol\"])\n        day0 = pd.Timestamp(context[\"date\"]).date()\n        later = [day for day in _daily_dates_for_symbol(daily_bars, symbol) if day > day0][: int(cfg.followup_sessions)]\n'''
new = '''    daily_dates_by_symbol = _daily_dates_by_symbol(daily_bars)\n    symbols_by_day: dict[date, set[str]] = {}\n    for context in contexts.to_dict(\"records\"):\n        symbol = str(context[\"symbol\"])\n        day0 = pd.Timestamp(context[\"date\"]).date()\n        later = [day for day in daily_dates_by_symbol.get(symbol, []) if day > day0][: int(cfg.followup_sessions)]\n'''
assert old in text
text = text.replace(old, new, 1)

old = '''    daily_dates_by_symbol = {\n        symbol: _daily_dates_for_symbol(daily_bars, symbol)\n        for symbol in signals[\"symbol\"].astype(str).unique()\n    }\n'''
new = '''    complete_daily_dates = _daily_dates_by_symbol(daily_bars)\n    daily_dates_by_symbol = {\n        symbol: complete_daily_dates.get(symbol, [])\n        for symbol in signals[\"symbol\"].astype(str).unique()\n    }\n'''
assert old in text
text = text.replace(old, new, 1)
research.write_text(text, encoding="utf-8")

runner = Path("scripts/run_strategy_research.py")
text = runner.read_text(encoding="utf-8")
old = '''    generate_dan_signal_set,\n    persist_dan_rule_identity,\n'''
new = '''    generate_dan_signal_set,\n    make_cached_symbol_minute_loader,\n    persist_dan_rule_identity,\n'''
assert old in text
text = text.replace(old, new, 1)

old = '''    study_meta: dict | None = None\n    study: MultiStrategyStudy | None = None\n\n    needs_price_volume = bool(selected & {\"orb\", \"vwap\"})\n    needs_dan = \"dan\" in selected\n'''
new = '''    study_meta: dict | None = None\n    study: MultiStrategyStudy | None = None\n\n    needs_price_volume = bool(selected & {\"orb\", \"vwap\"})\n    needs_dan = \"dan\" in selected\n    dan_minute_loader = (\n        make_cached_symbol_minute_loader(_load_minute_bars, max_days=24)\n        if needs_dan\n        else _load_symbol_minute_bars\n    )\n'''
assert old in text
text = text.replace(old, new, 1)

old = '''                study_meta,\n                _load_symbol_minute_bars,\n            )\n'''
new = '''                study_meta,\n                dan_minute_loader,\n            )\n'''
assert old in text
text = text.replace(old, new, 1)

old = '''                study_meta.get(\"split_end_dates\", {}),\n                _load_symbol_minute_bars,\n            )\n'''
new = '''                study_meta.get(\"split_end_dates\", {}),\n                dan_minute_loader,\n            )\n'''
assert old in text
text = text.replace(old, new, 1)
runner.write_text(text, encoding="utf-8")
