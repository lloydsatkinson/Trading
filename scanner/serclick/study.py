from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from .alpaca_rest import AlpacaCredentials, AlpacaRest
from .config import SerClickConfig
from .features import analyze_candidate_day, classify_early_day, prepare_bars

ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")


def _finite_or_zero(v) -> float:
    try:
        x = float(v)
        return x if np.isfinite(x) else 0.0
    except Exception:
        return 0.0


def _chunks(items: list[str], n: int):
    for i in range(0, len(items), n):
        yield items[i:i + n]


def _safe_symbol(s) -> bool:
    if not isinstance(s, str):
        return False
    s = s.strip()
    if not s or len(s) > 8:
        return False
    u = s.upper()
    bad_suffixes = ("W", "WS", "WT", "U", "R")
    if len(u) >= 5 and any(u.endswith(x) for x in bad_suffixes):
        return False
    return True


def _load_dotenv_if_available() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass


@dataclass
class StudyPaths:
    root: Path
    cache: Path
    output: Path
    db: Path

    @classmethod
    def build(cls, root: str | Path, db: str | Path) -> "StudyPaths":
        root = Path(root)
        cache = root / "data" / "cache" / "serclick_alpaca"
        output = root / "data" / "research" / "serclick_alpaca"
        db = Path(db)
        cache.mkdir(parents=True, exist_ok=True)
        output.mkdir(parents=True, exist_ok=True)
        db.parent.mkdir(parents=True, exist_ok=True)
        return cls(root=root, cache=cache, output=output, db=db)


class SerClickStudy:
    def __init__(
        self,
        root: str | Path = ".",
        db: str | Path = "data/sbe.db",
        feed: str = "sip",
        sessions: int = 60,
        end_date: str | None = None,
        cfg: SerClickConfig | None = None,
    ):
        _load_dotenv_if_available()
        self.cfg = cfg or SerClickConfig()
        self.feed = feed.lower()
        if self.feed not in {"sip", "iex"}:
            raise ValueError("feed must be 'sip' or 'iex'")
        self.sessions = sessions
        self.end_date = end_date
        self.paths = StudyPaths.build(root, db)
        creds = AlpacaCredentials.from_env()
        self.api = AlpacaRest(creds, pause_seconds=self.cfg.request_pause_seconds)
        self.run_id = f"serclick_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"

    def _completed_sessions(self) -> list[date]:
        today_et = datetime.now(ET).date()
        end = pd.Timestamp(self.end_date).date() if self.end_date else today_et
        now_et = datetime.now(ET)
        if end == today_et and now_et.time() < time(20, 5):
            end = today_et - timedelta(days=1)
        lookback = end - timedelta(days=max(120, self.sessions * 3))
        cal = self.api.calendar(str(lookback), str(end))
        if cal.empty:
            raise RuntimeError("Alpaca calendar returned no sessions")
        dates = sorted([d for d in cal["date"].tolist() if d <= end])
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
            raise RuntimeError("No Alpaca assets returned")
        df["symbol"] = df["symbol"].astype(str).str.upper()
        if "exchange" in df.columns:
            listed = {"NASDAQ", "NYSE", "AMEX", "ARCA", "BATS"}
            df = df[df["exchange"].astype(str).str.upper().isin(listed)]
        df = df[df["symbol"].map(_safe_symbol)]
        return df.drop_duplicates("symbol").reset_index(drop=True)

    def _daily_bars(self, symbols: list[str], sessions: list[date]) -> pd.DataFrame:
        cache = self.paths.cache / f"daily_{sessions[0]}_{sessions[-1]}_{self.feed}.csv.gz"
        if cache.exists():
            df = pd.read_csv(cache)
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
            return df
        start = datetime.combine(sessions[0] - timedelta(days=14), time(0, 0), ET).astimezone(UTC)
        end = datetime.combine(sessions[-1] + timedelta(days=1), time(0, 0), ET).astimezone(UTC)
        parts = []
        for j, batch in enumerate(_chunks(symbols, self.cfg.symbol_batch_size), 1):
            d = self.api.stock_bars(batch, "1Day", start, end, feed=self.feed, limit=self.cfg.api_limit)
            if not d.empty:
                parts.append(d)
            print(f"daily batch {j}: symbols={len(batch)} rows={len(d)}")
        df = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
        df.to_csv(cache, index=False, compression="gzip")
        return df

    def _prior_close_map(self, daily: pd.DataFrame) -> dict[tuple[str, date], float]:
        if daily.empty:
            return {}
        d = prepare_bars(daily).sort_values(["symbol", "timestamp"])
        d["session_date"] = d["timestamp_et"].dt.date
        d["prior_close"] = d.groupby("symbol")["close"].shift(1)
        return {(str(r.symbol), r.session_date): float(r.prior_close) for r in d.itertuples() if pd.notna(r.prior_close) and float(r.prior_close) > 0}

    def _prior_runner_map(self, daily: pd.DataFrame) -> dict[tuple[str, date], dict]:
        if daily.empty:
            return {}
        d = prepare_bars(daily).sort_values(["symbol", "timestamp"])
        d["session_date"] = d["timestamp_et"].dt.date
        d["prev_close"] = d.groupby("symbol")["close"].shift(1)
        d["extension"] = d["high"] / d["prev_close"]
        out: dict[tuple[str, date], dict] = {}
        for symbol, g in d.groupby("symbol", sort=False):
            g = g.reset_index(drop=True)
            for i in range(len(g)):
                day = g.loc[i, "session_date"]
                hist = g.iloc[max(0, i - 5):i]
                vals = hist["extension"].dropna()
                out[(str(symbol), day)] = {
                    "prior_1_5_max_extension": float(vals.max()) if not vals.empty else np.nan,
                    "prior_1_5_extreme_runner": bool((vals > self.cfg.extension_ratio).any()) if not vals.empty else False,
                }
        return out

    def _fetch_early_day(self, symbols: list[str], day: date) -> pd.DataFrame:
        cache = self.paths.cache / "early" / f"{day}_{self.feed}.csv.gz"
        cache.parent.mkdir(parents=True, exist_ok=True)
        if cache.exists():
            d = pd.read_csv(cache)
            if not d.empty:
                d["timestamp"] = pd.to_datetime(d["timestamp"], utc=True)
            return d
        start = datetime.combine(day, time(4, 0), ET).astimezone(UTC)
        end = datetime.combine(day, time(10, 0), ET).astimezone(UTC)
        parts = []
        for batch in _chunks(symbols, self.cfg.symbol_batch_size):
            d = self.api.stock_bars(batch, self.cfg.early_scan_timeframe, start, end, feed=self.feed, limit=self.cfg.api_limit)
            if not d.empty:
                parts.append(d)
        out = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
        out.to_csv(cache, index=False, compression="gzip")
        return out

    def _fetch_minute_day(self, symbols: list[str], day: date) -> pd.DataFrame:
        cache = self.paths.cache / "minute" / f"{day}_{self.feed}.csv.gz"
        cache.parent.mkdir(parents=True, exist_ok=True)
        if cache.exists():
            d = pd.read_csv(cache)
            if not d.empty:
                d["timestamp"] = pd.to_datetime(d["timestamp"], utc=True)
            return d
        start = datetime.combine(day, time(4, 0), ET).astimezone(UTC)
        end = datetime.combine(day, time(20, 0), ET).astimezone(UTC)
        parts = []
        for batch in _chunks(symbols, max(1, min(self.cfg.symbol_batch_size, 100))):
            d = self.api.stock_bars(batch, self.cfg.minute_timeframe, start, end, feed=self.feed, limit=self.cfg.api_limit)
            if not d.empty:
                parts.append(d)
        out = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
        out.to_csv(cache, index=False, compression="gzip")
        return out

    def _split_map(self, sessions: list[date]) -> dict[date, str]:
        n1 = self.cfg.development_sessions
        n2 = n1 + self.cfg.validation_sessions
        return {d: ("development" if i < n1 else "validation" if i < n2 else "test") for i, d in enumerate(sessions)}

    def _write_sqlite(self, name: str, df: pd.DataFrame) -> None:
        if df.empty:
            return
        x = df.copy()
        for c in x.columns:
            if pd.api.types.is_datetime64_any_dtype(x[c]):
                x[c] = x[c].astype(str)
        x.insert(0, "run_id", self.run_id)
        with sqlite3.connect(self.paths.db) as con:
            x.to_sql(name, con, if_exists="append", index=False)

    def run(self) -> dict:
        sessions = self._completed_sessions()
        split_map = self._split_map(sessions)
        assets = self._assets()
        symbols = assets["symbol"].tolist()
        print(f"run_id={self.run_id} feed={self.feed.upper()} sessions={sessions[0]}..{sessions[-1]} universe={len(symbols)}")

        daily = self._daily_bars(symbols, sessions)
        prior_close = self._prior_close_map(daily)
        prior_runner = self._prior_runner_map(daily)
        candidate_rows: list[dict] = []
        transition_frames: list[pd.DataFrame] = []
        event_frames: list[pd.DataFrame] = []

        for day_no, day in enumerate(sessions, 1):
            early = self._fetch_early_day(symbols, day)
            if early.empty:
                print(f"{day} early: 0 rows")
                continue
            early = prepare_bars(early)
            day_candidates: list[str] = []
            day_quals: dict[str, dict] = {}
            for symbol, g in early.groupby("symbol", sort=False):
                pc = prior_close.get((str(symbol), day))
                if pc is None or not (self.cfg.min_prior_close <= pc <= self.cfg.max_prior_close):
                    continue
                q = classify_early_day(g, pc, self.cfg)
                if not q or not q.get("extension_runner"):
                    continue
                q.update(prior_runner.get((str(symbol), day), {}))
                q.update({"symbol": str(symbol), "date": str(day), "split": split_map[day], "feed": self.feed.upper()})
                candidate_rows.append(q.copy())
                day_candidates.append(str(symbol))
                day_quals[str(symbol)] = q

            breadth20 = len(day_candidates)
            breadth50 = sum(1 for q in day_quals.values() if max(_finite_or_zero(q.get("pm_extension")), _finite_or_zero(q.get("hod_1000_extension"))) > 1.50)
            for q in day_quals.values():
                q["regime_breadth_20_at_1000"] = breadth20
                q["regime_breadth_50_at_1000"] = breadth50

            print(f"[{day_no:02d}/{len(sessions)}] {day} candidates={len(day_candidates)} leo_pm={sum(q['leo_pm_pass'] for q in day_quals.values())} leo_open={sum(q['leo_open_pass'] for q in day_quals.values())}")
            if not day_candidates:
                continue

            minute = self._fetch_minute_day(day_candidates, day)
            if minute.empty:
                continue
            for symbol, g in minute.groupby("symbol", sort=False):
                q = day_quals.get(str(symbol))
                if not q:
                    continue
                trans, events = analyze_candidate_day(g, q, self.cfg)
                if not trans.empty:
                    trans["split"] = split_map[day]
                    trans["feed"] = self.feed.upper()
                    transition_frames.append(trans)
                if not events.empty:
                    events["split"] = split_map[day]
                    events["feed"] = self.feed.upper()
                    events["regime_breadth_20_at_1000"] = q["regime_breadth_20_at_1000"]
                    events["regime_breadth_50_at_1000"] = q["regime_breadth_50_at_1000"]
                    events["prior_1_5_extreme_runner"] = q.get("prior_1_5_extreme_runner")
                    events["prior_1_5_max_extension"] = q.get("prior_1_5_max_extension")
                    event_frames.append(events)

        candidates = pd.DataFrame(candidate_rows)
        transitions = pd.concat(transition_frames, ignore_index=True) if transition_frames else pd.DataFrame()
        events = pd.concat(event_frames, ignore_index=True) if event_frames else pd.DataFrame()
        ignitions = pd.DataFrame()
        if not events.empty:
            ignitions = events[events["event_type"] == "IGNITION"].copy()
            if not ignitions.empty:
                ignitions = ignitions.sort_values(["date", "symbol", "timestamp"]).groupby(["date", "symbol"], as_index=False).first()

        summary = self._summarize(events, ignitions)
        out_dir = self.paths.output / self.run_id
        out_dir.mkdir(parents=True, exist_ok=True)
        candidates.to_csv(out_dir / "candidates.csv", index=False)
        transitions.to_csv(out_dir / "transitions.csv", index=False)
        events.to_csv(out_dir / "events_all.csv", index=False)
        ignitions.to_csv(out_dir / "ignitions_first.csv", index=False)
        summary.to_csv(out_dir / "summary.csv", index=False)
        (out_dir / "config.json").write_text(json.dumps(self.cfg.to_dict(), indent=2), encoding="utf-8")

        meta = pd.DataFrame([{
            "run_id": self.run_id,
            "feed": self.feed.upper(),
            "start_date": str(sessions[0]),
            "end_date": str(sessions[-1]),
            "sessions": len(sessions),
            "universe": len(symbols),
            "candidates": len(candidates),
            "events": len(events),
            "ignitions": len(ignitions),
            "output_dir": str(out_dir),
            "created_at": datetime.now(ET).isoformat(),
        }])
        meta.to_csv(out_dir / "run_meta.csv", index=False)

        self._write_sqlite("serclick_candidates", candidates)
        self._write_sqlite("serclick_transitions", transitions)
        self._write_sqlite("serclick_events", events)
        self._write_sqlite("serclick_ignitions", ignitions)
        self._write_sqlite("serclick_runs", meta.drop(columns=["run_id"]))
        print("DONE", meta.iloc[0].to_dict())
        return meta.iloc[0].to_dict()

    def _summarize(self, events: pd.DataFrame, ignitions: pd.DataFrame) -> pd.DataFrame:
        rows: list[dict] = []
        if events.empty:
            return pd.DataFrame()

        def emit(df: pd.DataFrame, label: str, dims: list[str]):
            if df.empty:
                return
            for keys, g in df.groupby(dims, dropna=False):
                if not isinstance(keys, tuple):
                    keys = (keys,)
                row = {"sample": label, "n": len(g)}
                row.update(dict(zip(dims, keys)))
                for c in [f"ret_{m}m" for m in self.cfg.forward_minutes] + ["ret_to_1600", "ret_to_2000", "mfe_to_2000", "mae_to_2000", "time_to_mfe_min"]:
                    if c in g.columns:
                        s = pd.to_numeric(g[c], errors="coerce")
                        row[f"mean_{c}"] = float(s.mean()) if s.notna().any() else np.nan
                        row[f"median_{c}"] = float(s.median()) if s.notna().any() else np.nan
                if "mfe_to_2000" in g.columns:
                    mfe = pd.to_numeric(g["mfe_to_2000"], errors="coerce")
                    row["hit_10pct"] = float((mfe >= 0.10).mean())
                    row["hit_20pct"] = float((mfe >= 0.20).mean())
                    row["hit_50pct"] = float((mfe >= 0.50).mean())
                rows.append(row)

        emit(events, "all_reclaims_and_ignitions", ["split", "event_type", "population"])
        if not ignitions.empty:
            emit(ignitions, "first_ignition", ["split", "population"])
            emit(ignitions, "first_ignition_by_window", ["split", "ignition_window"])
            emit(ignitions, "first_ignition_prior_runner", ["split", "prior_1_5_extreme_runner"])
        return pd.DataFrame(rows)