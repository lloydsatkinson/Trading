from pathlib import Path

path = Path("scanner/strategies/dan_irish/intraday.py")
text = path.read_text(encoding="utf-8")

old = '''def _regular_session(bars: pd.DataFrame) -> pd.DataFrame:\n    if bars.empty:\n        return bars.copy()\n    x = attach_session_vwap(bars)\n    clock = x["timestamp_et"].dt.time\n    return x[(clock >= pd.Timestamp("09:30").time()) & (clock < pd.Timestamp("16:00").time())].reset_index(drop=True)\n\n\ndef _breakout_level'''
new = '''def _regular_session(bars: pd.DataFrame) -> pd.DataFrame:\n    if bars.empty:\n        return bars.copy()\n    x = attach_session_vwap(bars)\n    clock = x["timestamp_et"].dt.time\n    return x[(clock >= pd.Timestamp("09:30").time()) & (clock < pd.Timestamp("16:00").time())].reset_index(drop=True)\n\n\ndef _prepare_intraday_features(bars: pd.DataFrame, cfg: DanConfig) -> pd.DataFrame:\n    x = _regular_session(bars)\n    if x.empty:\n        return x\n    x = x.copy()\n    x["prior_volume_median"] = rolling_prior_volume_median(x, cfg.volume_lookback_bars)\n    x["volume_ratio"] = pd.to_numeric(x["volume"], errors="coerce") / x["prior_volume_median"].replace(0, np.nan)\n    x["clv"] = x.apply(close_location_value, axis=1)\n    return x\n\n\ndef _breakout_level'''
assert old in text
text = text.replace(old, new, 1)

old = '''def generate_dan_intraday_signals(\n    bars: pd.DataFrame,\n    context: dict[str, Any],\n    cfg: DanConfig | None = None,\n    breakout_reference: str = "BASE_HIGH",\n) -> pd.DataFrame:'''
new = '''def generate_dan_intraday_signals(\n    bars: pd.DataFrame,\n    context: dict[str, Any],\n    cfg: DanConfig | None = None,\n    breakout_reference: str = "BASE_HIGH",\n    *,\n    _prepared_frame: pd.DataFrame | None = None,\n) -> pd.DataFrame:'''
assert old in text
text = text.replace(old, new, 1)

old = '''    x = _regular_session(bars)\n    if x.empty:\n        return pd.DataFrame()\n    x["prior_volume_median"] = rolling_prior_volume_median(x, cfg.volume_lookback_bars)\n    x["volume_ratio"] = pd.to_numeric(x["volume"], errors="coerce") / x["prior_volume_median"].replace(0, np.nan)\n    x["clv"] = x.apply(close_location_value, axis=1)\n    x["impulse_pct"] = pd.to_numeric(x["high"], errors="coerce") / prior_close - 1.0\n'''
new = '''    x = _prepared_frame.copy() if _prepared_frame is not None else _prepare_intraday_features(bars, cfg)\n    if x.empty:\n        return pd.DataFrame()\n'''
assert old in text
text = text.replace(old, new, 1)

old = '''    cfg = cfg or DanConfig()\n    frames: list[pd.DataFrame] = []\n    for minutes in consolidation_minutes:'''
new = '''    cfg = cfg or DanConfig()\n    prepared = _prepare_intraday_features(bars, cfg)\n    if prepared.empty:\n        return pd.DataFrame()\n    frames: list[pd.DataFrame] = []\n    for minutes in consolidation_minutes:'''
assert old in text
text = text.replace(old, new, 1)

old = '''                signal = generate_dan_intraday_signals(\n                    bars,\n                    context,\n                    combo,\n                    breakout_reference=str(reference),\n                )'''
new = '''                signal = generate_dan_intraday_signals(\n                    bars,\n                    context,\n                    combo,\n                    breakout_reference=str(reference),\n                    _prepared_frame=prepared,\n                )'''
assert old in text
text = text.replace(old, new, 1)

path.write_text(text, encoding="utf-8")
