from __future__ import annotations

import json

import pytest

from scanner.live.alpaca_stream import AlpacaSIPStream, AlpacaStreamError
from scanner.live.models import MarketBar
from scanner.serclick.alpaca_rest import AlpacaCredentials


class FakeSocket:
    def __init__(self, incoming: list[str]):
        self.incoming = list(incoming)
        self.sent: list[dict] = []
        self.closed = False

    def send(self, payload: str):
        self.sent.append(json.loads(payload))

    def recv(self):
        if not self.incoming:
            raise TimeoutError("fake socket exhausted")
        return self.incoming.pop(0)

    def settimeout(self, timeout: float):
        self.timeout = timeout

    def close(self):
        self.closed = True


class FakeFactory:
    def __init__(self, incoming: list[str]):
        self.incoming = incoming
        self.calls = 0
        self.socket: FakeSocket | None = None
        self.urls: list[str] = []

    def __call__(self, url: str, timeout: float):
        self.calls += 1
        self.urls.append(url)
        self.socket = FakeSocket(self.incoming)
        return self.socket


def control(msg: str, code: int | None = None) -> str:
    row = {"T": "success" if code is None else "error", "msg": msg}
    if code is not None:
        row["code"] = code
    return json.dumps([row])


def subscription(**kwargs) -> str:
    return json.dumps([{"T": "subscription", **kwargs}])


def creds() -> AlpacaCredentials:
    return AlpacaCredentials(key="SUPERKEY123", secret="SUPERSECRET456")


def test_one_socket_auth_then_subscribe():
    factory = FakeFactory(
        [
            control("connected"),
            control("authenticated"),
            subscription(bars=["*"], statuses=["*"], lulds=["*"]),
        ]
    )
    stream = AlpacaSIPStream(creds(), ws_factory=factory)

    stream.connect()
    stream.subscribe_initial()

    assert factory.calls == 1
    assert factory.urls == ["wss://stream.data.alpaca.markets/v2/sip"]
    assert factory.socket is not None
    assert factory.socket.sent[0] == {
        "action": "auth",
        "key": "SUPERKEY123",
        "secret": "SUPERSECRET456",
    }
    assert factory.socket.sent[1] == {
        "action": "subscribe",
        "bars": ["*"],
        "statuses": ["*"],
        "lulds": ["*"],
    }


def test_quotes_are_subscribed_by_delta_only():
    factory = FakeFactory(
        [
            control("connected"),
            control("authenticated"),
            subscription(bars=["*"], statuses=["*"], lulds=["*"]),
            subscription(bars=["*"], statuses=["*"], lulds=["*"], quotes=["ABC", "XYZ"]),
            subscription(bars=["*"], statuses=["*"], lulds=["*"], quotes=["ABC"]),
            subscription(bars=["*"], statuses=["*"], lulds=["*"], quotes=["ABC", "DEF"]),
        ]
    )
    stream = AlpacaSIPStream(creds(), ws_factory=factory)
    stream.connect()
    stream.subscribe_initial()

    stream.set_quote_symbols({"ABC", "XYZ"})
    stream.set_quote_symbols({"ABC", "DEF"})

    assert factory.socket is not None
    assert factory.socket.sent[-3:] == [
        {"action": "subscribe", "quotes": ["ABC", "XYZ"]},
        {"action": "unsubscribe", "quotes": ["XYZ"]},
        {"action": "subscribe", "quotes": ["DEF"]},
    ]


def test_406_connection_limit_is_specific_error():
    factory = FakeFactory([control("connected"), control("connection limit exceeded", 406)])
    stream = AlpacaSIPStream(creds(), ws_factory=factory)
    with pytest.raises(AlpacaStreamError, match="connection limit exceeded"):
        stream.connect()


def test_auth_error_is_secret_free():
    factory = FakeFactory([control("connected"), control("auth failed for account", 402)])
    stream = AlpacaSIPStream(creds(), ws_factory=factory)
    with pytest.raises(AlpacaStreamError) as exc:
        stream.connect()
    text = str(exc.value)
    assert "SUPERKEY123" not in text
    assert "SUPERSECRET456" not in text


def test_recv_events_decodes_market_data():
    market = json.dumps(
        [{"T": "b", "S": "ABC", "o": 2.0, "h": 2.2, "l": 1.9, "c": 2.1, "v": 1000, "t": "2026-09-02T14:35:00Z"}]
    )
    factory = FakeFactory([control("connected"), control("authenticated"), market])
    stream = AlpacaSIPStream(creds(), ws_factory=factory)
    stream.connect()
    events = stream.recv_events()
    assert len(events) == 1
    assert isinstance(events[0], MarketBar)
    assert events[0].symbol == "ABC"


def test_close_closes_the_single_socket():
    factory = FakeFactory([control("connected"), control("authenticated")])
    stream = AlpacaSIPStream(creds(), ws_factory=factory)
    stream.connect()
    stream.close()
    assert factory.socket is not None
    assert factory.socket.closed is True
