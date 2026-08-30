from __future__ import annotations

from typing import Iterable

import numpy as np

from .replay import ReplayRule

MAX_HOLD_MINUTES = (5, 10, 15, 30, 45, 60, 90, 120, 180, 240)
DEFAULT_STOP_PCTS = (0.03, 0.05, 0.07, 0.10, 0.15, 0.20, 0.30)
SERCLICK_STOP_PCTS = (0.03, 0.05, 0.07, 0.10, 0.15, 0.20, 0.30, 0.40, 0.50)
DEFAULT_TARGET_PCTS = (0.05, 0.10, 0.15, 0.20, 0.30, 0.40, 0.50)
DEFAULT_R_TARGETS = (1.0, 1.5, 2.0, 3.0, 4.0)


def common_percentage_rules(
    stop_pcts: Iterable[float] = DEFAULT_STOP_PCTS,
    target_pcts: Iterable[float] = DEFAULT_TARGET_PCTS,
    hold_minutes: Iterable[int] = MAX_HOLD_MINUTES,
    include_eod: bool = True,
) -> list[ReplayRule]:
    rules = [
        ReplayRule(stop_pct=float(stop), target_pct=float(target), max_hold_minutes=int(hold))
        for stop in stop_pcts
        for target in target_pcts
        for hold in hold_minutes
    ]
    if include_eod:
        rules.extend(
            ReplayRule(stop_pct=float(stop), target_pct=float(target), max_hold_minutes=None, hold_to_eod=True)
            for stop in stop_pcts
            for target in target_pcts
        )
    return rules


def structural_r_rules(
    signal: dict,
    r_targets: Iterable[float] = DEFAULT_R_TARGETS,
    hold_minutes: Iterable[int] = MAX_HOLD_MINUTES,
    include_eod: bool = True,
) -> list[ReplayRule]:
    try:
        stop = float(signal.get("stop_reference"))
    except (TypeError, ValueError):
        return []
    if not np.isfinite(stop) or stop <= 0:
        return []
    rules = [
        ReplayRule(stop_price=stop, target_r_multiple=float(r_target), max_hold_minutes=int(hold))
        for r_target in r_targets
        for hold in hold_minutes
    ]
    if include_eod:
        rules.extend(
            ReplayRule(stop_price=stop, target_r_multiple=float(r_target), max_hold_minutes=None, hold_to_eod=True)
            for r_target in r_targets
        )
    return rules


def default_rules_for_signal(signal: dict, serclick: bool = False) -> list[ReplayRule]:
    stops = SERCLICK_STOP_PCTS if serclick else DEFAULT_STOP_PCTS
    return common_percentage_rules(stop_pcts=stops) + structural_r_rules(signal)


def rule_family_id(rule: ReplayRule) -> str:
    """Return an aggregatable rule identity independent of a signal's price."""
    if rule.stop_price is not None:
        stop = "SSTRUCT"
    else:
        stop = f"S{int(round(float(rule.stop_pct or 0.0) * 100)):02d}"
    if rule.target_r_multiple is not None:
        target = f"R{float(rule.target_r_multiple):g}"
    elif rule.target_price is not None:
        target = "TSTRUCT"
    else:
        target = f"T{int(round(float(rule.target_pct or 0.0) * 100)):02d}"
    hold = "EOD" if rule.hold_to_eod else f"H{int(rule.max_hold_minutes)}"
    return f"{stop}_{target}_{hold}"
