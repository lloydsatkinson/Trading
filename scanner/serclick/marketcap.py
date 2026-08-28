from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo
import math
import re

import pandas as pd
import requests


ET = ZoneInfo("America/New_York")
NASDAQ_SCREENER_URL = "https://api.nasdaq.com/api/screener/stocks"
PROSPECTIVE_START = date(2026, 8, 28)
SNAPSHOT_COLUMNS = ["symbol", "market_cap", "market_cap_source", "market_cap_asof"]


def empty_snapshot() -> pd.DataFrame:
    return pd.DataFrame(columns=SNAPSHOT_COLUMNS)


def parse_market_cap(value: Any) -> float:
    if value is None:
        return math.nan
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            out = float(value)
        except (TypeError, ValueError):
            return math.nan
        return out if math.isfinite(out) and out >= 0 else math.nan

    text = str(value).strip().upper()
    if not text or text in {"N/A", "NA", "NONE", "NULL", "--", "-"}:
        return math.nan
    text = text.replace("$", "").replace(",", "").replace(" ", "")
    m = re.fullmatch(r"([+-]?\d+(?:\.\d+)?)([KMBT]?)", text)
    if not m:
        return math.nan
    number = float(m.group(1))
    if number < 0:
        return math.nan
    multiplier = {"": 1.0, "K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}[m.group(2)]
    return number * multiplier


def classify_market_cap(market_cap: Any) -> str:
    cap = parse_market_cap(market_cap)
    if not math.isfinite(cap):
        return "UNKNOWN"
    if cap < 300_000_000:
        return "MICROCAP"
    if cap < 2_000_000_000:
        return "SMALL_CAP"
    return "LARGER"


def enrich_market_caps(signals: pd.DataFrame, snapshot: pd.DataFrame) -> pd.DataFrame:
    out = signals.copy()
    if out.empty:
        return out

    out["symbol"] = out["symbol"].astype(str).str.upper()
    if snapshot is None or snapshot.empty:
        out["market_cap"] = math.nan
        out["market_cap_source"] = None
        out["market_cap_asof"] = None
        out["market_cap_bucket"] = "UNKNOWN"
        out["is_microcap"] = False
        return out

    snap = snapshot.copy()
    snap["symbol"] = snap["symbol"].astype(str).str.upper()
    snap["market_cap"] = snap["market_cap"].map(parse_market_cap)
    for col in ("market_cap_source", "market_cap_asof"):
        if col not in snap.columns:
            snap[col] = None
    snap = snap[SNAPSHOT_COLUMNS].drop_duplicates("symbol", keep="last")
    out = out.merge(snap, on="symbol", how="left")
    out["market_cap_bucket"] = out["market_cap"].map(classify_market_cap)
    out["is_microcap"] = out["market_cap_bucket"].eq("MICROCAP")
    return out


def should_enrich_prospectively(signal_day: Any, now: datetime | None = None, max_age_days: int = 3) -> bool:
    try:
        d = pd.Timestamp(signal_day).date()
    except Exception:
        return False
    now_et = now.astimezone(ET) if now is not None else datetime.now(ET)
    age = (now_et.date() - d).days
    return d >= PROSPECTIVE_START and 0 <= age <= max_age_days


def fetch_nasdaq_market_caps(session: requests.Session | None = None, timeout: int = 30) -> pd.DataFrame:
    s = session or requests.Session()
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; SerClickResearch/1.0)",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.nasdaq.com/market-activity/stocks/screener",
    }
    params = {"tableonly": "true", "limit": "10000", "download": "true"}
    response = s.get(NASDAQ_SCREENER_URL, params=params, headers=headers, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    rows = ((payload or {}).get("data") or {}).get("rows") or []
    observed = datetime.now(ET).isoformat()

    records: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = row.get("symbol") or row.get("Symbol")
        raw_cap = row.get("marketCap")
        if raw_cap is None:
            raw_cap = row.get("marketcap") or row.get("MarketCap")
        if not symbol:
            continue
        records.append({
            "symbol": str(symbol).upper(),
            "market_cap": parse_market_cap(raw_cap),
            "market_cap_source": "NASDAQ_SCREENER_CURRENT",
            "market_cap_asof": observed,
        })
    return pd.DataFrame(records).drop_duplicates("symbol", keep="last") if records else empty_snapshot()


def _snapshot_path(root: str | Path, signal_day: Any) -> Path:
    day = pd.Timestamp(signal_day).date().isoformat()
    return Path(root) / "data" / "cache" / "serclick_alpaca" / "fundamentals" / f"market_caps_{day}.csv.gz"


def load_or_fetch_market_cap_snapshot(
    root: str | Path,
    signal_day: Any,
    session: requests.Session | None = None,
) -> pd.DataFrame:
    if not should_enrich_prospectively(signal_day):
        return empty_snapshot()

    cache_file = _snapshot_path(root, signal_day)
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    if cache_file.exists():
        return pd.read_csv(cache_file)

    try:
        snapshot = fetch_nasdaq_market_caps(session=session)
    except Exception as exc:
        print(f"Market-cap enrichment unavailable: {type(exc).__name__}: {exc}")
        return empty_snapshot()

    if not snapshot.empty:
        snapshot.to_csv(cache_file, index=False, compression="gzip")
    return snapshot


def enrich_market_caps_from_history(root: str | Path, signals: pd.DataFrame) -> pd.DataFrame:
    """Attach only snapshots that were actually captured for each signal date.

    Missing dates remain UNKNOWN. This deliberately prevents a current market cap
    from being backfilled onto older historical signals.
    """
    if signals.empty:
        return signals.copy()
    if "date" not in signals.columns:
        return enrich_market_caps(signals, empty_snapshot())

    frames: list[pd.DataFrame] = []
    for day, group in signals.groupby(signals["date"].astype(str), sort=False):
        cache_file = _snapshot_path(root, day)
        snapshot = pd.read_csv(cache_file) if cache_file.exists() else empty_snapshot()
        frames.append(enrich_market_caps(group.copy(), snapshot))
    return pd.concat(frames, ignore_index=True) if frames else signals.copy()
