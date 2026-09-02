from __future__ import annotations

from typing import Mapping

from .models import (
    ConsensusSnapshot,
    Direction,
    FeedHealth,
    FeatureSnapshot,
    LiveSignalEvent,
    RankedOpportunity,
)


def _clamp(value: float) -> float:
    return max(0.0, min(100.0, float(value)))


def _participation_score(features: FeatureSnapshot) -> float:
    components: list[float] = []
    if features.rvol is not None:
        components.append(_clamp(float(features.rvol) * 10.0))
    if features.volume_acceleration is not None:
        components.append(_clamp(float(features.volume_acceleration) / 3.0 * 100.0))
    if not components:
        return 50.0
    return sum(components) / len(components)


def _catalyst_score(features: FeatureSnapshot) -> float:
    raw = features.context.get("catalyst_score")
    if raw is None:
        return 50.0
    try:
        return _clamp(float(raw))
    except (TypeError, ValueError):
        return 50.0


def _regime_score(event: LiveSignalEvent) -> float:
    metadata = event.intent.metadata
    if not metadata.get("regime_validated"):
        return 50.0
    raw = metadata.get("regime_score")
    try:
        return _clamp(float(raw))
    except (TypeError, ValueError):
        return 50.0


def rank_event(
    event: LiveSignalEvent,
    features: FeatureSnapshot,
    consensus: ConsensusSnapshot,
) -> float:
    evidence = _clamp(event.intent.descriptor.evidence_score)
    setup = _clamp(event.intent.setup_score)
    participation = _participation_score(features)
    catalyst = _catalyst_score(features)
    consensus_score = _clamp(consensus.weighted_score)
    execution = _clamp(event.intent.execution_score)
    regime = _regime_score(event)

    score = (
        0.35 * evidence
        + 0.20 * setup
        + 0.15 * participation
        + 0.10 * catalyst
        + 0.10 * consensus_score
        + 0.05 * execution
        + 0.05 * regime
    )

    if consensus.conflict:
        score -= 20.0

    score = _clamp(score)
    if event.feed_health in {
        FeedHealth.STALE,
        FeedHealth.DISCONNECTED,
        FeedHealth.RECOVERING,
    }:
        score = min(score, 49.0)
    return score


def rank_active(
    events: list[LiveSignalEvent] | tuple[LiveSignalEvent, ...],
    features_by_symbol: Mapping[str, FeatureSnapshot],
    consensus_by_side: Mapping[tuple[str, Direction], ConsensusSnapshot] | None = None,
) -> list[RankedOpportunity]:
    if consensus_by_side is None:
        from .consensus import build_consensus

        consensus_by_side = build_consensus(events)

    ranked: list[RankedOpportunity] = []
    for event in events:
        symbol = event.intent.symbol.upper()
        features = features_by_symbol.get(symbol) or features_by_symbol.get(event.intent.symbol)
        consensus = consensus_by_side.get((symbol, event.intent.descriptor.direction))
        if features is None or consensus is None:
            continue
        ranked.append(
            RankedOpportunity(
                event=event,
                score=rank_event(event, features, consensus),
                consensus=consensus,
            )
        )

    return sorted(
        ranked,
        key=lambda item: (item.score, item.event.source_timestamp),
        reverse=True,
    )
