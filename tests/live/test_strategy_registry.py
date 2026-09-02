from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from scanner.live.models import (
    Direction,
    ProductionStatus,
    StrategyDescriptor,
)
from scanner.live.strategy_registry import StrategyRegistry

ET = ZoneInfo("America/New_York")


class DummyAdapter:
    def __init__(self, descriptor):
        self.descriptor = descriptor

    def evaluate(self, state, features, prior_event):
        return None


def _descriptor(variant="ORB_LONG_BREAK"):
    return StrategyDescriptor(
        strategy_id="ORB",
        strategy_family="ORB",
        variant_id=variant,
        direction=Direction.LONG,
        strategy_version="orb-v1",
        production_status=ProductionStatus.PRODUCTION_ELIGIBLE,
        production_eligible=True,
        correlation_group="ORB",
        evidence_score=99.0,
    )


def test_registry_overrides_adapter_claims_with_authoritative_leaderboard():
    adapter = DummyAdapter(_descriptor())
    leaderboard = pd.DataFrame([{
        "strategy_id": "ORB",
        "variant_id": "ORB_LONG_BREAK",
        "direction": "LONG",
        "production_eligible": False,
        "robustness_score": 0.91,
    }])

    registry = StrategyRegistry.from_leaderboard([adapter], leaderboard)
    actual = registry.adapters[0].descriptor
    assert actual.production_eligible is False
    assert actual.production_status is ProductionStatus.RESEARCH
    assert actual.evidence_score == 91.0


def test_registry_marks_eligible_row_production_and_missing_row_research():
    eligible = DummyAdapter(_descriptor("ORB_LONG_BREAK"))
    missing = DummyAdapter(_descriptor("ORB_LONG_PULLBACK"))
    leaderboard = pd.DataFrame([{
        "strategy_id": "ORB",
        "variant_id": "ORB_LONG_BREAK",
        "direction": "LONG",
        "production_eligible": True,
        "robustness_score": 0.72,
    }])

    registry = StrategyRegistry.from_leaderboard([eligible, missing], leaderboard)
    by_variant = {adapter.descriptor.variant_id: adapter.descriptor for adapter in registry.adapters}

    assert by_variant["ORB_LONG_BREAK"].production_eligible is True
    assert by_variant["ORB_LONG_BREAK"].production_status is ProductionStatus.PRODUCTION_ELIGIBLE
    assert by_variant["ORB_LONG_BREAK"].evidence_score == 72.0

    assert by_variant["ORB_LONG_PULLBACK"].production_eligible is False
    assert by_variant["ORB_LONG_PULLBACK"].production_status is ProductionStatus.RESEARCH
    assert by_variant["ORB_LONG_PULLBACK"].evidence_score == 0.0
