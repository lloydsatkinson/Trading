from __future__ import annotations

from collections.abc import Callable

from .models import LiveSignalEvent


class SignalDispatchError(RuntimeError):
    def __init__(self, errors: list[Exception]) -> None:
        super().__init__(f"{len(errors)} signal subscriber(s) failed")
        self.errors = tuple(errors)


class SignalBus:
    def __init__(self) -> None:
        self._subscribers: list[Callable[[LiveSignalEvent], None]] = []
        self._published_event_ids: set[str] = set()

    def subscribe(self, callback: Callable[[LiveSignalEvent], None]) -> None:
        self._subscribers.append(callback)

    def publish(self, event: LiveSignalEvent) -> None:
        if event.event_id in self._published_event_ids:
            return

        self._published_event_ids.add(event.event_id)
        errors: list[Exception] = []
        for callback in self._subscribers:
            try:
                callback(event)
            except Exception as exc:
                errors.append(exc)
        if errors:
            raise SignalDispatchError(errors)
