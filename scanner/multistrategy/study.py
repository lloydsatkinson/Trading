from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from scanner.core.features import opening_range, prepare_intraday_bars
from scanner.core.models import market_cap_bucket, price_bucket
from scanner.core.validation import chronological_split
from scanner.strategies.dan_irish.config import DanConfig
from .config import MultiStrategyConfig

ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")


def _chunks(items: list[str], n: int) -> Iterable[list[str]]:
    for i in range(0, len(items), n):
        yield items[i:i + n]


def _safe_symbol(symbol) -> bool:
    if not isinstance(symbol, str):
        return False
    symbol = symbol.strip()
    if not symbol or len(symbol) > 8:
        return False
    upper = symbol.upper()
    if len(upper) >= 5 and any(upper.endswith(suffix) for suffix in ("W", "WS", "WT", "U", "R")):
        return False
    return True


def _opening_history_start(day: date | str, lookback_sessions: int = 20) -> date:
    """Give the first research day enough prior calendar room for a full RVOL baseline."""
    target = pd.Timestamp(day).date()
    calendar_days = max(60, int(lookback_sessions) * 4)
    return target - timedelta(days=calendar_days)


def _split_end_dates(split_map: dict[date, str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for day, split in split_map.items():
        current = out.get(str(split))
        if current is None or day > pd.Timestamp(current).date():
            out[str(split)] = str(day)
    return out


def _bar_dollar(x: pd.DataFrame) -> pd.Series:
    typical = (x["high"] + x["low"] + x["close"]) / 3.0
    if "vwap" in x.columns:
        price = pd.to_numeric(x["vwap"], errors="coerce").where(lambda s: s > 0).fillna(typical)
    else:
        price = typical
    return pd.to_numeric(x["volume"], errors="coerce").fillna(0.0) * price.fillna(x["close"])


def broad_candidate_context(
    early: pd.DataFrame,
    prior_close: float,
    cfg: MultiStrategyConfig | None = None,
    optional: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = cfg or MultiStrategyConfig()
    optional = optional or {}
    if early.empty or not np.isfinite(prior_close) or prior_close <= 0:
        return {"broad_candidate": False, "float_shares": optional.get("float_shares"), "catalyst_class": optional.get("catalyst_class", "UNKNOWN")}
    x = prepare_intraday_bars(early)
    x["bar_dollar"] = _bar_dollar(x)
    tod = x["timestamp_et"].dt.time
    pm = x[tod < time(9, 30)].copy()
    open30 = x[(tod >= time(9, 30)) & (tod < time(10, 0))].copy()
    through10 = x[tod < time(10, 0)].copy()

    pm_high = float(pm["high"].max()) if not pm.empty else np.nan
    pm_low = float(pm["low"].min()) if not pm.empty else np.nan
    pm_volume = float(pm["volume"].sum()) if not pm.empty else 0.0
    pm_dollar = float(pm["bar_dollar"].sum()) if not pm.empty else 0.0
    open30_dollar = float(open30["bar_dollar"].sum()) if not open30.empty else 0.0
    open30_volume = float(open30["volume"].sum()) if not open30.empty else 0.0

    if not pm.empty:
        gap_reference = float(pm.sort_values("timestamp_et").iloc[-1]["close"])
    elif not open30.empty:
        gap_reference = float(open30.sort_values("timestamp_et").iloc[0]["open"])
    else:
        gap_reference = np.nan
    gap_pct = gap_reference / prior_close - 1.0 if np.isfinite(gap_reference) else np.nan
    hod10 = float(through10["high"].max()) if not through10.empty else np.nan
    max_extension = np.nanmax([
        pm_high / prior_close if np.isfinite(pm_high) else np.nan,
        hod10 / prior_close if np.isfinite(hod10) else np.nan,
    ])
    leo_extension_runner = bool(np.isfinite(max_extension) and max_extension > 1.20)
    activity = max(pm_dollar, open30_dollar)
    broad_candidate = bool(
        np.isfinite(gap_pct)
        and abs(gap_pct) >= cfg.min_gap_pct
        and activity >= cfg.min_activity_dollar_turnover
        and cfg.min_price <= prior_close <= cfg.max_price
    )
    return {
        "prior_close": float(prior_close),
        "pm_high": pm_high,
        "pm_low": pm_low,
        "pm_volume": pm_volume,
        "pm_dollar_turnover": pm_dollar,
        "pm_gap_pct": float(gap_pct) if np.isfinite(gap_pct) else np.nan,
        "open30_volume": open30_volume,
        "open30_dollar_turnover": open30_dollar,
        "hod_1000": hod10,
        "broad_candidate": broad_candidate,
        "leo_extension_runner": leo_extension_runner,
        "float_shares": optional.get("float_shares"),
        "catalyst_class": optional.get("catalyst_class", "UNKNOWN") or "UNKNOWN",
    }


def dan_candidate_context(
    early: pd.DataFrame,
    prior_close: float,
    cfg: DanConfig | None = None,
    optional: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = cfg or DanConfig()
    optional = optional or {}
    if early.empty or not np.isfinite(prior_close) or prior_close <= 0:
        return {
            "dan_candidate": False,
            "price_bucket": price_bucket(prior_close),
            "float_shares": optional.get("float_shares"),
            "catalyst_class": optional.get("catalyst_class", "UNKNOWN") or "UNKNOWN",
        }
    relaxed = MultiStrategyConfig(
        min_gap_pct=0.0,
        min_activity_dollar_turnover=0.0,
        min_price=0.01,
        max_price=1_000_000.0,
    )
    base = broad_candidate_context(early, prior_close, relaxed, optional)
    pm_high = base.get("pm_high", np.nan)
    hod10 = base.get("hod_1000", np.nan)
    extension = np.nanmax([
        float(pm_high) / prior_close if np.isfinite(pm_high) else np.nan,
        float(hod10) / prior_close if np.isfinite(hod10) else np.nan,
    ])
    activity = max(float(base.get("pm_dollar_turnover") or 0.0), float(base.get("open30_dollar_turnover") or 0.0))
    base["dan_candidate"] = bool(
        np.isfinite(extension)
        and extension >= 1.0 + cfg.min_reference_extension_pct
        and activity >= cfg.min_activity_dollar_turnover
    )
    base["price_bucket"] = price_bucket(prior_close)
    return base


def opening_baseline_for_day(
    history: pd.DataFrame,
    symbol: str,
    day: date | str,
    lookback_sessions: int = 20,
) -> dict[str, float | int]:
    if history.empty:
        return {"history_n": 0, "median_opening5_volume": np.nan, "median_opening5_dollar_turnover": np.nan}
    target = pd.Timestamp(day).date()
    x = history.copy()
    x["date_value"] = pd.to_datetime(x["date"], errors="coerce").dt.date
    x = x[x["symbol"].astype(str).eq(str(symbol)) & x["date_value"].lt(target)].sort_values("date_value").tail(lookback_sessions)
    return {
        "history_n": int(len(x)),
        "median_opening5_volume": float(pd.to_numeric(x["opening5_volume"], errors="coerce").median()) if not x.empty else np.nan,
        "median_opening5_dollar_turnover": float(pd.to_numeric(x["opening5_dollar_turnover"], errors="coerce").median()) if not x.empty else np.nan,
    }


def opening5_row(bars: pd.DataFrame, symbol: str, day: date | str) -> dict[str, Any]:
    stats = opening_range(bars, minutes=5)
    return {
        "symbol": str(symbol),
        "date": str(pd.Timestamp(day).date()),
        "opening5_volume": float(stats["volume"]),
        "opening5_dollar_turnover": float(stats["dollar_turnover"]),
    }


@dataclass(frozen=True)
class MultiStrategyPaths:
    root: Path
    cache: Path
    output: Path

    @classmethod
    def build(cls, root: str | Path) -> "MultiStrategyPaths":
        root = Path(root)
        cache = root / "data" / "cache" / "multistrategy_alpaca"
        output = root / "data" / "research" / "multistrategy"
        cache.mkdir(parents=True, exist_ok=True)
        output.mkdir(parents=True, exist_ok=True)
        return cls(root, cache, output)


class MultiStrategyStudy:
    def __init__(self, root: str | Path = ".", feed: str = "sip", sessions: int = 60, end_date: str | None = None, cfg: MultiStrategyConfig | None = None):
        self.cfg = cfg or MultiStrategyConfig()
        self.feed = feed.lower()
        if self.feed not in {"sip", "iex"}:
            raise ValueError("feed must be 'sip' or 'iex'")
        self.sessions = int(sessions)
        self.end_date = end_date
        self.paths = MultiStrategyPaths.build(root)
        self.run_id = f"multistrategy_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        self._api = None

    @property
    def api(self):
        if self._api is None:
            from scanner.serclick.alpaca_rest import AlpacaCredentials, AlpacaRest
            self._api = AlpacaRest(AlpacaCredentials.from_env(), pause_seconds=self.cfg.request_pause_seconds)
        return self._api

    def _completed_sessions(self) -> list[date]:
        today = datetime.now(ET).date()
        end = pd.Timestamp(self.end_date).date() if self.end_date else today
        if end == today and datetime.now(ET).time() < time(20, 5):
            end -= timedelta(days=1)
        lookback = end - timedelta(days=max(120, self.sessions * 3))
        cal = self.api.calendar(str(lookback), str(end))
        dates = sorted(d for d in cal.get("date", []) if d <= end)
        if len(dates) < self.sessions:
            raise RuntimeError(f"Only {len(dates)} sessions available; need {self.sessions}")
        return dates[-self.sessions:]

    def _assets(self) -> pd.DataFrame:
        cache = self.paths.cache / "assets.csv"
        if cache.exists():
            df = pd.read_csv(cache)
        else:
            df = self.api.assets(include_inactive=True)
            df.to_csv(cache, index=False)
        if df.empty:
            return df
        if "symbol" not in df.columns:
            return df.iloc[0:0].copy()
        df = df[df["symbol"].map(_safe_symbol)].copy()
        df["symbol"] = df["symbol"].map(lambda value: value.strip().upper())
        if "exchange" in df.columns:
            df = df[df["exchange"].astype(str).str.upper().isin({"NASDAQ", "NYSE", "AMEX", "ARCA", "BATS"})]
        return df.drop_duplicates("symbol").reset_index(drop=True)

    def _daily_bars(self, symbols: list[str], sessions: list[date]) -> pd.DataFrame:
        cache = self.paths.cache / f"daily_{sessions[0]}_{sessions[-1]}_{self.feed}.csv.gz"
        if cache.exists():
            out = pd.read_csv(cache)
            if not out.empty:
                out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True)
            return out
        start = datetime.combine(sessions[0] - timedelta(days=14), time(0), ET).astimezone(UTC)
        end = datetime.combine(sessions[-1] + timedelta(days=1), time(0), ET).astimezone(UTC)
        parts = [self.api.stock_bars(batch, "1Day", start, end, feed=self.feed, limit=self.cfg.api_limit) for batch in _chunks(symbols, self.cfg.symbol_batch_size)]
        out = pd.concat([p for p in parts if not p.empty], ignore_index=True) if any(not p.empty for p in parts) else pd.DataFrame()
        out.to_csv(cache, index=False, compression="gzip")
        return out

    def _prior_close_map(self, daily: pd.DataFrame) -> dict[tuple[str, date], float]:
        if daily.empty:
            return {}
        x = prepare_intraday_bars(daily).sort_values(["symbol", "timestamp_et"])
        x["prior_close"] = x.groupby("symbol")["close"].shift(1)
        return {(str(r.symbol), r.session_date): float(r.prior_close) for r in x.itertuples() if pd.notna(r.prior_close) and float(r.prior_close) > 0}

    def _fetch_early_day(self, symbols: list[str], day: date) -> pd.DataFrame:
        cache = self.paths.cache / "early" / f"{day}_{self.feed}.csv.gz"
        cache.parent.mkdir(parents=True, exist_ok=True)
        if cache.exists():
            out = pd.read_csv(cache)
            if not out.empty:
                out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True)
            return out
        start = datetime.combine(day, time(4), ET).astimezone(UTC)
        end = datetime.combine(day, time(10), ET).astimezone(UTC)
        parts = [self.api.stock_bars(batch, self.cfg.early_scan_timeframe, start, end, feed=self.feed, limit=self.cfg.api_limit) for batch in _chunks(symbols, self.cfg.symbol_batch_size)]
        out = pd.concat([p for p in parts if not p.empty], ignore_index=True) if any(not p.empty for p in parts) else pd.DataFrame()
        out.to_csv(cache, index=False, compression="gzip")
        return out

    def ensure_minute_day(self, symbols: list[str], day: date) -> pd.DataFrame:
        requested = sorted({str(symbol) for symbol in symbols if symbol})
        cache = self.paths.cache / "minute" / f"{day}_{self.feed}.csv.gz"
        manifest = self.paths.cache / "minute" / f"{day}_{self.feed}.symbols.json"
        cache.parent.mkdir(parents=True, exist_ok=True)

        existing = pd.DataFrame()
        if cache.exists():
            existing = pd.read_csv(cache)
            if not existing.empty:
                existing["timestamp"] = pd.to_datetime(existing["timestamp"], utc=True)

        manifested: set[str] = set()
        if manifest.exists():
            try:
                manifested = {str(value) for value in json.loads(manifest.read_text(encoding="utf-8"))}
            except (TypeError, ValueError, json.JSONDecodeError):
                manifested = set()
        missing = sorted(set(requested) - manifested)
        if missing:
            start = datetime.combine(day, time(4), ET).astimezone(UTC)
            end = datetime.combine(day, time(20), ET).astimezone(UTC)
            parts = [
                self.api.stock_bars(batch, self.cfg.minute_timeframe, start, end, feed=self.feed, limit=self.cfg.api_limit)
                for batch in _chunks(missing, min(self.cfg.symbol_batch_size, 100))
            ]
            fresh = pd.concat([part for part in parts if not part.empty], ignore_index=True) if any(not part.empty for part in parts) else pd.DataFrame()
            frames = [frame for frame in (existing, fresh) if not frame.empty]
            out = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
            if not out.empty:
                out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True)
                out = out.drop_duplicates(["symbol", "timestamp"], keep="last").sort_values(["symbol", "timestamp"]).reset_index(drop=True)
            out.to_csv(cache, index=False, compression="gzip")
            manifest.write_text(json.dumps(sorted(set(manifested) | set(requested))), encoding="utf-8")
            return out
        return existing

    def _fetch_minute_day(self, symbols: list[str], day: date) -> pd.DataFrame:
        return self.ensure_minute_day(symbols, day)

    def _fetch_opening_history(self, symbols: list[str], sessions: list[date], through_day: date) -> pd.DataFrame:
        if not symbols:
            return pd.DataFrame(columns=["symbol", "date", "opening5_volume", "opening5_dollar_turnover"])
        if not sessions:
            return pd.DataFrame()
        start_day = _opening_history_start(sessions[0], self.cfg.opening_baseline_sessions)
        digest = hashlib.sha1("\n".join(sorted(symbols)).encode("utf-8")).hexdigest()[:12]
        key = f"{start_day}_{through_day}_{self.feed}_{digest}.csv.gz"
        cache = self.paths.cache / "opening5" / key
        cache.parent.mkdir(parents=True, exist_ok=True)
        if cache.exists():
            return pd.read_csv(cache)
        start = datetime.combine(start_day, time(9, 30), ET).astimezone(UTC)
        end = datetime.combine(through_day, time(9, 36), ET).astimezone(UTC)
        parts = [self.api.stock_bars(batch, self.cfg.opening_history_timeframe, start, end, feed=self.feed, limit=self.cfg.api_limit) for batch in _chunks(symbols, min(self.cfg.symbol_batch_size, 100))]
        raw = pd.concat([p for p in parts if not p.empty], ignore_index=True) if any(not p.empty for p in parts) else pd.DataFrame()
        rows: list[dict[str, Any]] = []
        if not raw.empty:
            prepared = prepare_intraday_bars(raw)
            for (symbol, day), g in prepared.groupby(["symbol", "session_date"], sort=True):
                clock = g["timestamp_et"].dt.time
                window = g[(clock >= time(9, 30)) & (clock < time(9, 35))]
                if window.empty:
                    continue
                volume = pd.to_numeric(window["volume"], errors="coerce").fillna(0.0)
                dollars = _bar_dollar(window)
                rows.append({"symbol": str(symbol), "date": str(day), "opening5_volume": float(volume.sum()), "opening5_dollar_turnover": float(dollars.sum())})
        out = pd.DataFrame(rows)
        out.to_csv(cache, index=False, compression="gzip")
        return out

    def run(self, include_dan_candidates: bool = False) -> dict[str, Any]:
        sessions = self._completed_sessions()
        split_map = chronological_split(sessions, self.cfg.development_sessions, self.cfg.validation_sessions, self.cfg.test_sessions)
        assets = self._assets()
        symbols = assets["symbol"].tolist()
        daily = self._daily_bars(symbols, sessions)
        prior_close = self._prior_close_map(daily)
        contexts: list[dict[str, Any]] = []
        dan_contexts: list[dict[str, Any]] = []
        minute_files: list[str] = []

        for day in sessions:
            early = self._fetch_early_day(symbols, day)
            if early.empty:
                continue
            early = prepare_intraday_bars(early)
            day_contexts: list[dict[str, Any]] = []
            day_dan_contexts: list[dict[str, Any]] = []

            for symbol, group in early.groupby("symbol", sort=False):
                pc = prior_close.get((str(symbol), day))
                if pc is None:
                    continue
                common = {"symbol": str(symbol), "date": str(day), "split": split_map[day], "feed": self.feed.upper()}

                broad = broad_candidate_context(group, pc, self.cfg)
                if broad.get("broad_candidate"):
                    broad.update(common)
                    day_contexts.append(broad)

                if include_dan_candidates:
                    dan = dan_candidate_context(group, pc)
                    if dan.get("dan_candidate"):
                        dan.update(common)
                        day_dan_contexts.append(dan)

            all_day_contexts = day_contexts + day_dan_contexts
            if not all_day_contexts:
                continue

            from scanner.serclick.marketcap import load_or_fetch_market_cap_snapshot
            snapshot = load_or_fetch_market_cap_snapshot(self.paths.root, day)
            cap_map = {}
            if snapshot is not None and not snapshot.empty:
                for record in snapshot.to_dict("records"):
                    cap_map[str(record.get("symbol", "")).upper()] = record
            for ctx in all_day_contexts:
                cap_row = cap_map.get(str(ctx["symbol"]).upper(), {})
                cap = cap_row.get("market_cap", np.nan)
                ctx["market_cap"] = cap
                ctx["market_cap_bucket"] = market_cap_bucket(cap)
                ctx["market_cap_source"] = cap_row.get("market_cap_source")
                ctx["market_cap_asof"] = cap_row.get("market_cap_asof")

            candidate_symbols = sorted({str(row["symbol"]) for row in all_day_contexts})
            opening_history = self._fetch_opening_history(candidate_symbols, sessions, day)
            minute = self.ensure_minute_day(candidate_symbols, day)
            minute_cache = self.paths.cache / "minute" / f"{day}_{self.feed}.csv.gz"
            minute_files.append(str(minute_cache))

            for target, day_rows in ((contexts, day_contexts), (dan_contexts, day_dan_contexts)):
                for ctx in day_rows:
                    symbol = str(ctx["symbol"])
                    symbol_bars = minute[minute["symbol"].astype(str).eq(symbol)].copy() if not minute.empty else pd.DataFrame()
                    current = opening5_row(symbol_bars, symbol, day) if not symbol_bars.empty else {"opening5_volume": np.nan, "opening5_dollar_turnover": np.nan}
                    baseline = opening_baseline_for_day(opening_history, symbol, day, self.cfg.opening_baseline_sessions)
                    median_volume = baseline["median_opening5_volume"]
                    ctx.update(current)
                    ctx.update(baseline)
                    ctx["opening_rvol"] = float(current["opening5_volume"] / median_volume) if np.isfinite(current["opening5_volume"]) and np.isfinite(median_volume) and median_volume > 0 else np.nan
                    target.append(ctx)

        output_dir = self.paths.output / self.run_id
        output_dir.mkdir(parents=True, exist_ok=True)
        context_df = pd.DataFrame(contexts)
        context_df.to_csv(output_dir / "candidate_contexts.csv", index=False)

        result = {
            "run_id": self.run_id,
            "feed": self.feed.upper(),
            "sessions": len(sessions),
            "start_date": str(sessions[0]),
            "end_date": str(sessions[-1]),
            "candidate_contexts": context_df,
            "minute_files": minute_files,
            "output_dir": str(output_dir),
        }
        if include_dan_candidates:
            dan_df = pd.DataFrame(dan_contexts)
            dan_df.to_csv(output_dir / "dan_candidate_contexts.csv", index=False)
            result.update({
                "dan_candidate_contexts": dan_df,
                "daily_bars": daily,
                "split_end_dates": _split_end_dates(split_map),
                "session_splits": {str(day): str(split) for day, split in split_map.items()},
            })
        return result
