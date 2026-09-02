from __future__ import annotations

import json
from datetime import datetime, timezone
from math import isfinite
from typing import Any

from .models import MarketBar, MarketLuld, MarketQuote, MarketStatus


class ProtocolError(ValueError):
    pass


_HALT_CODES = {"2", "H", "P"}
_RESUME_CODES = {"3", "Q", "T"}
_CONTROL_TYPES = {"success", "error", "subscription"}


def _timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ProtocolError("Alpaca message timestamp is missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ProtocolError(f"invalid Alpaca message timestamp: {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ProtocolError("Alpaca message timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _symbol(value: Any) -> str:
    symbol = str(value or "").strip().upper()
    if not symbol:
        raise ProtocolError("Alpaca data message symbol is missing")
    return symbol


def _nonnegative(value: Any, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ProtocolError(f"{field} must be a nonnegative number") from exc
    if not isfinite(number) or number < 0:
        raise ProtocolError(f"{field} must be a nonnegative number")
    return number


def _status_halted(code: str, message: str) -> bool:
    normalized = code.strip().upper()
    if normalized in _HALT_CODES:
        return True
    if normalized in _RESUME_CODES:
        return False
    text = message.strip().lower()
    if "resum" in text or "reopen" in text:
        return False
    return "halt" in text or "pause" in text


def _decode_row(row: dict[str, Any]):
    message_type = str(row.get("T") or "")
    if message_type in _CONTROL_TYPES:
        return dict(row)

    if message_type == "b":
        return MarketBar(
            symbol=_symbol(row.get("S")),
            timestamp=_timestamp(row.get("t")),
            open=_nonnegative(row.get("o"), "open"),
            high=_nonnegative(row.get("h"), "high"),
            low=_nonnegative(row.get("l"), "low"),
            close=_nonnegative(row.get("c"), "close"),
            volume=_nonnegative(row.get("v"), "volume"),
        )

    if message_type == "q":
        return MarketQuote(
            symbol=_symbol(row.get("S")),
            timestamp=_timestamp(row.get("t")),
            bid=_nonnegative(row.get("bp"), "bid"),
            ask=_nonnegative(row.get("ap"), "ask"),
            bid_size=_nonnegative(row.get("bs"), "bid_size"),
            ask_size=_nonnegative(row.get("as"), "ask_size"),
        )

    if message_type == "s":
        code = str(row.get("sc") or "")
        message = str(row.get("sm") or "")
        return MarketStatus(
            symbol=_symbol(row.get("S")),
            timestamp=_timestamp(row.get("t")),
            halted=_status_halted(code, message),
            code=code,
            message=message,
            reason_code=str(row.get("rc") or ""),
            reason_message=str(row.get("rm") or ""),
        )

    if message_type == "l":
        return MarketLuld(
            symbol=_symbol(row.get("S")),
            timestamp=_timestamp(row.get("t")),
            limit_up=_nonnegative(row.get("u"), "limit_up"),
            limit_down=_nonnegative(row.get("d"), "limit_down"),
            indicator=str(row.get("i") or ""),
        )

    return {
        "type": "UNKNOWN_ALPACA_MESSAGE",
        "message_type": message_type or "UNKNOWN",
        "symbol": str(row.get("S") or "").upper(),
    }


def decode_alpaca_payload(payload: str | bytes) -> list[MarketBar | MarketQuote | MarketStatus | MarketLuld | dict[str, Any]]:
    if isinstance(payload, bytes):
        try:
            payload = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProtocolError("Alpaca payload is not UTF-8") from exc
    try:
        decoded = json.loads(payload)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ProtocolError("Alpaca payload is not valid JSON") from exc
    if not isinstance(decoded, list):
        raise ProtocolError("Alpaca payload must be an array of messages")

    events = []
    for row in decoded:
        if not isinstance(row, dict):
            raise ProtocolError("Alpaca message must be an object")
        events.append(_decode_row(row))
    return events
