"""Shared research primitives for multi-strategy studies."""

from .models import SignalRecord, market_cap_bucket, market_cap_in_primary_universe
from .validation import chronological_split, selectable_splits

__all__ = [
    "SignalRecord",
    "market_cap_bucket",
    "market_cap_in_primary_universe",
    "chronological_split",
    "selectable_splits",
]
