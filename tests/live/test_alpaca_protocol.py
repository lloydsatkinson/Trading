from __future__ import annotations

import json

import pytest

from scanner.live.alpaca_protocol import ProtocolError, decode_alpaca_payload
from scanner.live.models import MarketBar, MarketLuld, MarketQuote, MarketStatus


def test_decode_stock_stream_payload():
    raw = json.dumps(
        [
            {"T": "b", "S": "ABC", "o": 2.0, "h": 2.4, "l": 1.9, "c": 2.3, "v": 1000, "t": "2026-09-02T14:35:00Z"},
            {"T": "q", "S": "ABC", "bp": 2.29, "ap": 2.31, "bs": 10, "as": 12, "t": "2026-09-02T14:35:05Z"},
            {"T": "s", "S": "ABC", "sc": "H", "sm": "Trading Halt", "rc": "T12", "rm": "Trading Halted", "t": "2026-09-02T14:35:06Z"},
            {"T": "l", "S": "ABC", "u": 2.60, "d": 2.10, "i": "B", "t": "2026-09-02T14:35:07Z"},
        ]
    )

    events = decode_alpaca_payload(raw)

    assert isinstance(events[0], MarketBar)
    assert events[0].symbol == "ABC"
    assert events[0].close == 2.3
    assert events[0].timestamp.utcoffset().total_seconds() == 0
    assert isinstance(events[1], MarketQuote)
    assert events[1].ask == 2.31
    assert isinstance(events[2], MarketStatus)
    assert events[2].halted is True
    assert events[2].reason_code == "T12"
    assert isinstance(events[3], MarketLuld)
    assert events[3].limit_up == 2.60
    assert events[3].limit_down == 2.10


@pytest.mark.parametrize(
    ("code", "message", "halted"),
    [
        ("2", "Trading Halt", True),
        ("3", "Resume", False),
        ("H", "Trading Halt", True),
        ("P", "Volatility Trading Pause", True),
        ("Q", "Quotation Resumption", False),
        ("T", "Trading Resumption", False),
    ],
)
def test_trading_status_code_mapping(code: str, message: str, halted: bool):
    raw = json.dumps([{"T": "s", "S": "ABC", "sc": code, "sm": message, "t": "2026-09-02T14:35:06Z"}])
    event = decode_alpaca_payload(raw)[0]
    assert isinstance(event, MarketStatus)
    assert event.halted is halted


def test_unknown_data_message_is_preserved_as_diagnostic():
    event = decode_alpaca_payload(json.dumps([{"T": "z", "S": "ABC", "x": 1}]))[0]
    assert event["type"] == "UNKNOWN_ALPACA_MESSAGE"
    assert event["message_type"] == "z"


def test_negative_market_price_is_rejected():
    raw = json.dumps([{"T": "q", "S": "ABC", "bp": -1.0, "ap": 2.0, "bs": 1, "as": 1, "t": "2026-09-02T14:35:05Z"}])
    with pytest.raises(ProtocolError, match="nonnegative"):
        decode_alpaca_payload(raw)


def test_malformed_timestamp_is_rejected():
    raw = json.dumps([{"T": "b", "S": "ABC", "o": 2.0, "h": 2.1, "l": 1.9, "c": 2.0, "v": 100, "t": "not-a-time"}])
    with pytest.raises(ProtocolError, match="timestamp"):
        decode_alpaca_payload(raw)
