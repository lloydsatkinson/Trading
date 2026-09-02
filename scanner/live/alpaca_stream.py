from __future__ import annotations

import json
from typing import Any, Callable

from scanner.serclick.alpaca_rest import AlpacaCredentials

from .alpaca_protocol import ProtocolError, decode_alpaca_payload


class AlpacaStreamError(RuntimeError):
    pass


def _default_ws_factory(url: str, timeout: float):
    import websocket

    return websocket.create_connection(url, timeout=timeout)


class AlpacaSIPStream:
    def __init__(
        self,
        creds: AlpacaCredentials,
        feed: str = "sip",
        ws_factory: Callable[..., Any] | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        normalized_feed = str(feed).strip().lower()
        if not normalized_feed:
            raise ValueError("feed must be non-empty")
        self.creds = creds
        self.feed = normalized_feed
        self.timeout_seconds = float(timeout_seconds)
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.url = f"wss://stream.data.alpaca.markets/v2/{self.feed}"
        self._ws_factory = ws_factory or _default_ws_factory
        self._socket = None
        self._authenticated = False
        self._initial_subscribed = False
        self._quote_symbols: set[str] = set()

    def _safe_text(self, value: Any) -> str:
        text = str(value or "Alpaca stream error")
        for secret in (self.creds.key, self.creds.secret):
            if secret:
                text = text.replace(secret, "***")
        return text

    def _raise_control_error(self, row: dict[str, Any]) -> None:
        code = row.get("code")
        message = self._safe_text(row.get("msg") or "Alpaca stream error")
        if str(code) == "406":
            raise AlpacaStreamError("connection limit exceeded")
        if code is None:
            raise AlpacaStreamError(message)
        raise AlpacaStreamError(f"Alpaca stream error {code}: {message}")

    def _recv(self):
        if self._socket is None:
            raise AlpacaStreamError("stream is not connected")
        try:
            payload = self._socket.recv()
        except (TimeoutError, OSError) as exc:
            raise AlpacaStreamError("Alpaca stream timed out or disconnected") from exc
        try:
            return decode_alpaca_payload(payload)
        except ProtocolError as exc:
            raise AlpacaStreamError(f"invalid Alpaca stream payload: {exc}") from exc

    def _send(self, row: dict[str, Any]) -> None:
        if self._socket is None:
            raise AlpacaStreamError("stream is not connected")
        self._socket.send(json.dumps(row, separators=(",", ":")))

    def _expect_success(self, message: str) -> None:
        decoded = self._recv()
        for event in decoded:
            if not isinstance(event, dict):
                continue
            if event.get("T") == "error":
                self._raise_control_error(event)
            if event.get("T") == "success" and str(event.get("msg") or "").lower() == message.lower():
                return
        raise AlpacaStreamError(f"expected Alpaca success message: {message}")

    def _expect_subscription(self) -> dict[str, Any]:
        decoded = self._recv()
        for event in decoded:
            if not isinstance(event, dict):
                continue
            if event.get("T") == "error":
                self._raise_control_error(event)
            if event.get("T") == "subscription":
                return event
        raise AlpacaStreamError("expected Alpaca subscription confirmation")

    def connect(self) -> None:
        self.close()
        try:
            self._socket = self._ws_factory(self.url, timeout=self.timeout_seconds)
            if hasattr(self._socket, "settimeout"):
                self._socket.settimeout(self.timeout_seconds)
            self._expect_success("connected")
            self._send({"action": "auth", "key": self.creds.key, "secret": self.creds.secret})
            self._expect_success("authenticated")
        except AlpacaStreamError:
            self.close()
            raise
        except Exception as exc:
            self.close()
            raise AlpacaStreamError(f"unable to connect to Alpaca stream: {self._safe_text(exc)}") from exc
        self._authenticated = True

    def subscribe_initial(self) -> None:
        if not self._authenticated:
            raise AlpacaStreamError("stream must authenticate before subscribing")
        self._send({"action": "subscribe", "bars": ["*"], "statuses": ["*"], "lulds": ["*"]})
        self._expect_subscription()
        self._initial_subscribed = True

    def set_quote_symbols(self, symbols: set[str]) -> None:
        if not self._initial_subscribed:
            raise AlpacaStreamError("initial stream subscription is not active")
        desired = {str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()}
        remove = sorted(self._quote_symbols - desired)
        add = sorted(desired - self._quote_symbols)
        if remove:
            self._send({"action": "unsubscribe", "quotes": remove})
            self._expect_subscription()
            self._quote_symbols.difference_update(remove)
        if add:
            self._send({"action": "subscribe", "quotes": add})
            self._expect_subscription()
            self._quote_symbols.update(add)

    def recv_events(self):
        decoded = self._recv()
        for event in decoded:
            if isinstance(event, dict) and event.get("T") == "error":
                self._raise_control_error(event)
        return decoded

    @property
    def quote_symbols(self) -> frozenset[str]:
        return frozenset(self._quote_symbols)

    def close(self) -> None:
        socket = self._socket
        self._socket = None
        self._authenticated = False
        self._initial_subscribed = False
        self._quote_symbols.clear()
        if socket is not None:
            try:
                socket.close()
            except Exception:
                pass
