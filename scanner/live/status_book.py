from __future__ import annotations

from .models import MarketLuld, MarketQuote, MarketStatus


class StatusBook:
    def __init__(self) -> None:
        self._quotes: dict[str, MarketQuote] = {}
        self._statuses: dict[str, MarketStatus] = {}
        self._lulds: dict[str, MarketLuld] = {}

    def update_quote(self, quote: MarketQuote) -> None:
        self._quotes[quote.symbol.upper()] = quote

    def update_status(self, status: MarketStatus) -> None:
        self._statuses[status.symbol.upper()] = status

    def update_luld(self, luld: MarketLuld) -> None:
        self._lulds[luld.symbol.upper()] = luld

    def quote(self, symbol: str) -> MarketQuote | None:
        return self._quotes.get(str(symbol).upper())

    def status(self, symbol: str) -> MarketStatus | None:
        return self._statuses.get(str(symbol).upper())

    def luld(self, symbol: str) -> MarketLuld | None:
        return self._lulds.get(str(symbol).upper())

    def is_halted(self, symbol: str) -> bool:
        status = self.status(symbol)
        return bool(status.halted) if status is not None else False

    def spread_pct(self, symbol: str) -> float | None:
        quote = self.quote(symbol)
        if quote is None:
            return None
        midpoint = (float(quote.bid) + float(quote.ask)) / 2.0
        if midpoint <= 0 or quote.ask < quote.bid:
            return None
        return (float(quote.ask) - float(quote.bid)) / midpoint

    def luld_distance_pct(self, symbol: str) -> float | None:
        quote = self.quote(symbol)
        bands = self.luld(symbol)
        if quote is None or bands is None:
            return None
        midpoint = (float(quote.bid) + float(quote.ask)) / 2.0
        if midpoint <= 0:
            return None
        distances = []
        if bands.limit_up >= midpoint:
            distances.append((float(bands.limit_up) - midpoint) / midpoint)
        if bands.limit_down <= midpoint:
            distances.append((midpoint - float(bands.limit_down)) / midpoint)
        if not distances:
            return 0.0
        return min(distances)
