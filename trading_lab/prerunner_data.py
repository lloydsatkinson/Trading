from __future__ import annotations

import hashlib
import math
from typing import Iterable

import numpy as np
import pandas as pd


def _clean(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"ticker", "previous_close", "prior20_median_volume"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"missing {sorted(missing)}")
    x = frame.copy()
    x["ticker"] = x["ticker"].astype(str).str.upper()
    for c in ("previous_close", "prior20_median_volume", "high", "low", "close"):
        if c in x.columns:
            x[c] = pd.to_numeric(x[c], errors="coerce")
    return x.drop_duplicates("ticker", keep="last").reset_index(drop=True)


def identify_cases(
    frame: pd.DataFrame,
    long_threshold: float = 0.20,
    short_threshold: float = 0.20,
) -> pd.DataFrame:
    """Mark retrospective event cases; this function is not a signal generator."""
    if not (0 < long_threshold < 1 and 0 < short_threshold < 1):
        raise ValueError("case thresholds must be between 0 and 1")
    x = _clean(frame)
    if "high" not in x.columns or "low" not in x.columns:
        raise ValueError("case identification requires same-day high and low")
    prev = x["previous_close"]
    valid = prev > 0
    x["case_long"] = valid & (x["high"] / prev - 1.0 >= long_threshold)
    x["case_short"] = valid & (1.0 - x["low"] / prev >= short_threshold)
    return x


def _eligible_prior_only(frame: pd.DataFrame, min_price: float, max_price: float, min_prior_volume: float) -> pd.DataFrame:
    x = _clean(frame)
    return x[
        x["previous_close"].between(min_price, max_price, inclusive="both")
        & (x["prior20_median_volume"] >= min_prior_volume)
    ].copy()


def _distance(case: pd.Series, control: pd.Series) -> float:
    cp, xp = float(case["previous_close"]), float(control["previous_close"])
    cv, xv = float(case["prior20_median_volume"]), float(control["prior20_median_volume"])
    if cp <= 0 or xp <= 0 or cv <= 0 or xv <= 0:
        return math.inf
    return abs(math.log(xp / cp)) + 0.5 * abs(math.log(xv / cv))


def _stable_rank(session_date: str, ticker: str) -> str:
    return hashlib.sha256(f"{session_date}|{ticker}".encode("utf-8")).hexdigest()


def select_controls(
    frame: pd.DataFrame,
    case_tickers: Iterable[str],
    controls_per_case: int = 3,
    session_date: str = "",
    min_controls_per_day: int = 0,
    min_price: float = 0.75,
    max_price: float = 20.0,
    min_prior_volume: float = 50_000.0,
) -> list[str]:
    """Select controls using prior price/liquidity fields only.

    Same-day high/low/close are deliberately ignored. Cases are matched by log-price
    and log-volume distance; quiet days use a deterministic hash rank so the dataset
    retains ordinary base-rate context.
    """
    if controls_per_case < 0 or min_controls_per_day < 0:
        raise ValueError("control counts cannot be negative")
    x = _eligible_prior_only(frame, min_price, max_price, min_prior_volume)
    cases = {str(t).upper() for t in case_tickers}
    pool = x[~x["ticker"].isin(cases)].copy()
    by_ticker = x.set_index("ticker", drop=False)
    chosen: list[str] = []
    used: set[str] = set()

    for ticker in sorted(cases):
        if ticker not in by_ticker.index:
            continue
        case = by_ticker.loc[ticker]
        scored = []
        for _, control in pool.iterrows():
            ct = str(control["ticker"])
            if ct in used:
                continue
            scored.append((_distance(case, control), ct))
        scored.sort(key=lambda z: (z[0], z[1]))
        for _, ct in scored[:controls_per_case]:
            chosen.append(ct)
            used.add(ct)

    need = max(0, int(min_controls_per_day) - len(chosen))
    if need:
        rest = [str(t) for t in pool["ticker"] if str(t) not in used]
        rest.sort(key=lambda t: (_stable_rank(str(session_date), t), t))
        chosen.extend(rest[:need])
    return chosen


def build_case_control_manifest(
    frame: pd.DataFrame,
    session_date: str,
    controls_per_case: int = 3,
    min_controls_per_day: int = 10,
    long_threshold: float = 0.20,
    short_threshold: float = 0.20,
    min_price: float = 0.75,
    max_price: float = 20.0,
    min_prior_volume: float = 50_000.0,
) -> pd.DataFrame:
    marked = identify_cases(frame, long_threshold=long_threshold, short_threshold=short_threshold)
    eligible = _eligible_prior_only(marked, min_price, max_price, min_prior_volume)
    cases = eligible[eligible["case_long"] | eligible["case_short"]].copy()
    case_tickers = set(cases["ticker"])
    controls = select_controls(
        eligible,
        case_tickers,
        controls_per_case=controls_per_case,
        session_date=session_date,
        min_controls_per_day=min_controls_per_day,
        min_price=min_price,
        max_price=max_price,
        min_prior_volume=min_prior_volume,
    )
    selected = list(dict.fromkeys(sorted(case_tickers) + controls))
    if not selected:
        return pd.DataFrame(columns=list(marked.columns) + ["session_date", "selection_role"])
    out = marked[marked["ticker"].isin(selected)].copy()
    out["session_date"] = str(session_date)
    out["selection_role"] = np.where(out["ticker"].isin(case_tickers), "case", "control")
    order = {ticker: i for i, ticker in enumerate(selected)}
    out["_order"] = out["ticker"].map(order)
    return out.sort_values("_order").drop(columns="_order").reset_index(drop=True)
