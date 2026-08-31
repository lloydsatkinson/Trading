from __future__ import annotations

from typing import Any, Mapping

import numpy as np

from scanner.core.multisession_replay import SwingReplayRule

HOLD_SESSIONS = (1, 2, 3, 4, 5, 7, 10)
PERCENT_STOPS = (0.05, 0.08, 0.10, 0.15, 0.20)
PERCENT_TARGETS = (0.05, 0.10, 0.15, 0.20, 0.30, 0.40, 0.50)
R_TARGETS = (1.0, 1.5, 2.0, 3.0, 4.0)


def _finite_positive(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) and number > 0 else None


def default_dan_swing_rules(signal: Mapping[str, Any]) -> list[SwingReplayRule]:
    """Return the fixed V1 Dan swing replay grid.

    Signal qualification and exit-rule selection remain separate identities. The
    grid deliberately spans fixed percentage risk, percentage targets, R targets,
    and every approved hold horizon. When a structural stop is available it gets
    its own R-target family rather than being silently mixed with percentage risk.
    """
    rules: list[SwingReplayRule] = []
    structural_stop = _finite_positive(signal.get("stop_reference"))

    for hold in HOLD_SESSIONS:
        for stop_pct in PERCENT_STOPS:
            for target_pct in PERCENT_TARGETS:
                rules.append(
                    SwingReplayRule(
                        stop_mode="PCT",
                        stop_pct=stop_pct,
                        target_pct=target_pct,
                        max_hold_sessions=hold,
                    )
                )
            for target_r in R_TARGETS:
                rules.append(
                    SwingReplayRule(
                        stop_mode="PCT",
                        stop_pct=stop_pct,
                        target_r_multiple=target_r,
                        max_hold_sessions=hold,
                    )
                )

        if structural_stop is not None:
            for target_r in R_TARGETS:
                rules.append(
                    SwingReplayRule(
                        stop_mode="STRUCTURAL",
                        stop_price=structural_stop,
                        target_r_multiple=target_r,
                        max_hold_sessions=hold,
                    )
                )

    # Rule IDs are the persisted exit-rule identity. Fail loudly if a future
    # change accidentally creates two parameter combinations with the same ID.
    ids = [rule.rule_id for rule in rules]
    if len(ids) != len(set(ids)):
        raise RuntimeError("Dan swing replay grid contains duplicate rule identities")
    return rules
