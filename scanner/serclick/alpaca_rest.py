from __future__ import annotations

import os
import re
import time
from pathlib import Path
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

import pandas as pd
import requests
from dotenv import load_dotenv


class AlpacaError(RuntimeError):
    pass


@dataclass
class AlpacaCredentials:
    key: str
    secret: str
    trading_base: str = "https://paper-api.alpaca.markets"
    data_base: str = "https://data.alpaca.markets"

    @classmethod
    def from_env(cls) -> "AlpacaCredentials":
        project_env = Path(__file__).resolve().parents[2] / ".env"
        if project_env.exists():
            load_dotenv(project_env, override=False)

        key = os.getenv("APCA_API_KEY_ID") or os.getenv("ALPACA_API_KEY") or os.getenv("ALPACA_KEY_ID")
        secret = os.getenv("APCA_API_SECRET_KEY") or os.getenv("ALPACA_API_SECRET") or os.getenv("ALPACA_SECRET_KEY")
        if not key or not secret:
            raise AlpacaError(
                "Alpaca credentials not found. Set APCA_API_KEY_ID and "
                "APCA_API_SECRET_KEY (or ALPACA_API_KEY / ALPACA_API_SECRET)."
            )
        return cls(
            key=key,
            secret=secret,
            trading_base=os.getenv("APCA_API_BASE_URL", "https://paper-api.alpaca.markets").rstrip("/"),
            data_base=os.getenv("ALPACA_DATA_BASE_URL", "https://data.alpaca.markets").rstrip("/"),
        )


class AlpacaRest:
    def __init__(self, creds: AlpacaCredentials, pause_seconds: float = 0.05):
        self.creds = creds
        self.pause_seconds = pause_seconds
        self.session = requests.Session()
        self.session.headers.update(
            {
                "APCA-API-KEY-ID": creds.key,
                "APCA-API-SECRET-KEY": creds.secret,
                "Accept": "application/json",
            }
        )

    def _get(self, url: str, params: dict | None = None) -> dict | list:
        last_error: Exception | None = None
        for attempt in range(6):
            try:
                r = self.session.get(url, params=params, timeout=60)
                if r.status_code == 429:
                    time.sleep(min(2 ** attempt, 20))
                    continue
                if 400 <= r.status_code < 500:
                    detail = r.text.strip() if getattr(r, "text", None) else ""
                    raise AlpacaError(
                        f"Alpaca request failed: {url} params={params}: "
                        f"HTTP {r.status_code} {detail}"
                    )
                r.raise_for_status()
                time.sleep(self.pause_seconds)
                return r.json()
            except AlpacaError:
                raise
            except Exception as exc:
                last_error = exc
                if attempt == 5:
                    break
                time.sleep(min(2 ** attempt, 10))
        raise AlpacaError(f"Alpaca request failed: {url} params={params}: {last_error}")

    def assets(self, include_inactive: bool = True) -> pd.DataFrame:
        statuses = ["active", "inactive"] if include_inactive else ["active"]
        rows: list[dict] = []
        for status in statuses:
            payload = self._get(
                f"{self.creds.trading_base}/v2/assets",
                params={"asset_class": "us_equity", "status": status},
            )
            if not isinstance(payload, list):
                raise AlpacaError(f"Unexpected assets payload: {type(payload)!r}")
            rows.extend(payload)
        df = pd.DataFrame(rows)
        if df.empty:
            return df
        for c in ("symbol", "exchange", "status", "name"):
            if c not in df.columns:
                df[c] = None
        return df

    def calendar(self, start: str, end: str) -> pd.DataFrame:
        payload = self._get(
            f"{self.creds.trading_base}/v2/calendar",
            params={"start": start, "end": end},
        )
        df = pd.DataFrame(payload)
        if not df.empty:
            df["date"] = pd.to_datetime(df["date"]).dt.date
        return df

    def corporate_actions(
        self,
        symbols: Iterable[str],
        start: datetime | str,
        end: datetime | str,
        types: Iterable[str] = ("reverse_split", "forward_split", "unit_split"),
        limit: int = 1_000,
    ) -> pd.DataFrame:
        symbols = [str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()]
        action_types = [str(value).strip() for value in types if str(value).strip()]
        if not symbols or not action_types:
            return pd.DataFrame(columns=["symbol", "action_type", "action_date"])

        params = {
            "symbols": ",".join(symbols),
            "types": ",".join(action_types),
            "start": str(pd.Timestamp(start).date()),
            "end": str(pd.Timestamp(end).date()),
            "sort": "asc",
            "limit": int(limit),
        }
        key_to_type = {
            "reverse_splits": "reverse_split",
            "forward_splits": "forward_split",
            "unit_splits": "unit_split",
        }
        rows: list[dict] = []
        page_token: str | None = None
        while True:
            if page_token:
                params["page_token"] = page_token
            else:
                params.pop("page_token", None)
            payload = self._get(f"{self.creds.data_base}/v1/corporate-actions", params=params)
            if not isinstance(payload, dict):
                raise AlpacaError(f"Unexpected corporate-actions payload: {type(payload)!r}")
            groups = payload.get("corporate_actions") or {}
            if not isinstance(groups, dict):
                raise AlpacaError(f"Unexpected corporate_actions body: {type(groups)!r}")
            for key, items in groups.items():
                action_type = key_to_type.get(str(key))
                if action_type is None or action_type not in action_types:
                    continue
                for item in items or []:
                    row = dict(item)
                    row["action_type"] = action_type
                    row["action_date"] = row.get("ex_date") or row.get("process_date") or row.get("record_date")
                    rows.append(row)
            page_token = payload.get("next_page_token")
            if not page_token:
                break

        if not rows:
            return pd.DataFrame(columns=["symbol", "action_type", "action_date"])
        out = pd.DataFrame(rows)
        if "symbol" not in out.columns:
            out["symbol"] = None
        out["symbol"] = out["symbol"].astype(str).str.upper()
        out["action_date"] = pd.to_datetime(out["action_date"], errors="coerce").dt.date
        return out.sort_values(["symbol", "action_date", "action_type"]).reset_index(drop=True)

    def stock_bars(
        self,
        symbols: Iterable[str],
        timeframe: str,
        start: datetime | str,
        end: datetime | str,
        feed: str = "sip",
        adjustment: str = "raw",
        limit: int = 10_000,
    ) -> pd.DataFrame:
        symbols = [s for s in symbols if s]
        if not symbols:
            return pd.DataFrame()
        active_symbols = list(symbols)
        params = {
            "symbols": ",".join(active_symbols),
            "timeframe": timeframe,
            "start": pd.Timestamp(start).isoformat(),
            "end": pd.Timestamp(end).isoformat(),
            "feed": feed,
            "adjustment": adjustment,
            "sort": "asc",
            "limit": int(limit),
        }
        rows: list[dict] = []
        page_token: str | None = None
        while True:
            if not active_symbols:
                break
            params["symbols"] = ",".join(active_symbols)
            if page_token:
                params["page_token"] = page_token
            elif "page_token" in params:
                params.pop("page_token")
            try:
                payload = self._get(f"{self.creds.data_base}/v2/stocks/bars", params=params)
            except AlpacaError as exc:
                match = re.search(r"invalid symbol:\s*([A-Za-z0-9.\-]+)", str(exc), flags=re.IGNORECASE)
                if match:
                    bad_symbol = match.group(1).upper()
                    remaining = [s for s in active_symbols if s.upper() != bad_symbol]
                    if len(remaining) != len(active_symbols):
                        print(f"Skipping Alpaca-invalid symbol: {bad_symbol}")
                        active_symbols = remaining
                        page_token = None
                        continue
                raise
            if not isinstance(payload, dict):
                raise AlpacaError(f"Unexpected bars payload: {type(payload)!r}")
            bars_by_symbol = payload.get("bars") or {}
            for symbol, bars in bars_by_symbol.items():
                for b in bars or []:
                    rows.append(
                        {
                            "symbol": symbol,
                            "timestamp": b.get("t"),
                            "open": b.get("o"),
                            "high": b.get("h"),
                            "low": b.get("l"),
                            "close": b.get("c"),
                            "volume": b.get("v"),
                            "trade_count": b.get("n"),
                            "vwap": b.get("vw"),
                        }
                    )
            page_token = payload.get("next_page_token")
            if not page_token:
                break
        if not rows:
            return pd.DataFrame(
                columns=["symbol", "timestamp", "open", "high", "low", "close", "volume", "trade_count", "vwap"]
            )
        df = pd.DataFrame(rows)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        for c in ("open", "high", "low", "close", "volume", "trade_count", "vwap"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
        return df.sort_values(["symbol", "timestamp"]).reset_index(drop=True)
