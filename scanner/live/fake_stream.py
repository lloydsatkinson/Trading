from __future__ import annotations

from collections.abc import Iterable, Iterator

from .models import MarketBar


class FakeMarketStream:
    """Deterministic, API-free completed-bar stream for replay and safety tests."""

    def __init__(self, events: Iterable[MarketBar]) -> None:
        self._events = tuple(events)
        if not all(isinstance(event, MarketBar) for event in self._events):
            raise TypeError("FakeMarketStream accepts MarketBar events only")

    def __iter__(self) -> Iterator[MarketBar]:
        return iter(self._events)

    def __len__(self) -> int:
        return len(self._events)
