from __future__ import annotations

from collections import defaultdict

from .models import ConsensusSnapshot, Direction, LifecycleState, LiveSignalEvent

_ACTIVE_STATES = {
    LifecycleState.WATCH,
    LifecycleState.ARMED,
    LifecycleState.FIRE,
    LifecycleState.MANAGE,
}
_MULTIPLIERS = (1.0, 0.35)


def _multiplier(index: int) -> float:
    if index < len(_MULTIPLIERS):
        return _MULTIPLIERS[index]
    return 0.15


def build_consensus(
    events: list[LiveSignalEvent] | tuple[LiveSignalEvent, ...],
) -> dict[tuple[str, Direction], ConsensusSnapshot]:
    grouped: dict[tuple[str, Direction], list[LiveSignalEvent]] = defaultdict(list)
    active_directions: dict[str, set[Direction]] = defaultdict(set)

    for event in events:
        if event.effective_state not in _ACTIVE_STATES:
            continue
        symbol = event.intent.symbol.upper()
        direction = event.intent.descriptor.direction
        grouped[(symbol, direction)].append(event)
        active_directions[symbol].add(direction)

    result: dict[tuple[str, Direction], ConsensusSnapshot] = {}
    for (symbol, direction), side_events in grouped.items():
        by_group: dict[str, list[LiveSignalEvent]] = defaultdict(list)
        for event in side_events:
            by_group[event.intent.descriptor.correlation_group].append(event)

        total = 0.0
        production_families = 0
        supporting: list[str] = []
        for group_name, group_events in sorted(by_group.items()):
            supporting.append(group_name)
            ordered = sorted(
                group_events,
                key=lambda event: event.intent.setup_score,
                reverse=True,
            )
            for index, event in enumerate(ordered):
                total += max(0.0, min(100.0, float(event.intent.setup_score))) * _multiplier(index)
            if any(event.intent.descriptor.production_eligible for event in group_events):
                production_families += 1

        family_count = len(by_group)
        conflict = len(active_directions[symbol]) > 1
        if conflict:
            label = "CONFLICT"
        elif family_count >= 3:
            label = "MULTI_EDGE"
        elif family_count == 2:
            label = "CONFIRMED"
        else:
            label = "SINGLE_EDGE"

        result[(symbol, direction)] = ConsensusSnapshot(
            symbol=symbol,
            direction=direction,
            active_families=family_count,
            production_families=production_families,
            weighted_score=max(0.0, min(100.0, total / 2.0)),
            supporting_families=tuple(supporting),
            conflict=conflict,
            confidence_label=label,
        )

    return result
