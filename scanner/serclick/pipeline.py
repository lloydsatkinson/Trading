from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pandas as pd

from .replay import ReplayRule, default_rule_grid, replay_signal_grid
from .reporting import attach_variants


def run_replay_from_cache(
    root: str | Path,
    feed: str,
    ignitions: pd.DataFrame,
    rules: Iterable[ReplayRule] | None = None,
) -> pd.DataFrame:
    if ignitions.empty:
        return pd.DataFrame()

    root = Path(root)
    rules = list(rules or default_rule_grid())
    cache_dir = root / "data" / "cache" / "serclick_alpaca" / "minute"
    frames: list[pd.DataFrame] = []

    for day, day_signals in ignitions.groupby(ignitions["date"].astype(str), sort=True):
        cache_file = cache_dir / f"{day}_{feed.lower()}.csv.gz"
        if not cache_file.exists():
            continue
        bars = pd.read_csv(cache_file)
        if bars.empty:
            continue
        bars["symbol"] = bars["symbol"].astype(str)
        for signal in day_signals.to_dict("records"):
            symbol_bars = bars[bars["symbol"].eq(str(signal["symbol"]))].copy()
            if symbol_bars.empty:
                continue
            frames.append(replay_signal_grid(symbol_bars, signal, rules=rules))

    raw = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return attach_variants(raw)
