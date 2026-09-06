from __future__ import annotations

from typing import Any, Mapping

import numpy as np

from scanner.core.multisession_replay import SwingReplayRule

HOLD_SESSIONS = (1, 2, 3, 4, 5, 7, 10)
PERCENT_STOPS = (0.05, 0.08, 0.10, 0.15, 0.20)
PERCENT_TARGETS = (0.05, 0.10, 0.15, 0.20, 0.30, 0.40, 0.50)
R_TARGETS = (1.0, 1.5, 2.0, 3.0, 4.0)
ATR_MULTIPLES = (1.0, 1.5, 2.0)


def _finite_positive(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) and number > 0 else None


def _long_stop(value: Any, entry: float | None) -> float | None:
    stop = _finite_positive(value)
    if stop is None or entry is None or stop >= entry:
        return None
    return stop


def default_dan_swing_rules(signal: Mapping[str, Any]) -> list[SwingReplayRule]:
    """Return the Dan swing replay grid with auditable stop/exit identities.

    Percentage controls remain intact. Structural and dynamic families are only
    emitted when their required pre-entry state is available. No stop level is
    inferred from future bars.
    """
    rules: list[SwingReplayRule] = []
    entry = _finite_positive(signal.get("entry_price_slipped"))
    # Preserve the historical rule-builder contract for callers that only provide
    # a structural stop. Production signals do carry an entry, in which case the
    # long-side sanity check still rejects a stop at/above the actual entry.
    structural_stop = (
        _finite_positive(signal.get("stop_reference"))
        if entry is None
        else _long_stop(signal.get("stop_reference"), entry)
    )
    prior_day_low = _long_stop(signal.get("prior_day_low"), entry)
    day0_support = _long_stop(signal.get("day0_support"), entry)
    anchored_vwap = _long_stop(signal.get("anchored_vwap_at_entry"), entry)
    pre_entry_atr = _finite_positive(signal.get("pre_entry_atr"))
    anchor_pv = _finite_positive(signal.get("anchored_vwap_seed_pv"))
    anchor_volume = _finite_positive(signal.get("anchored_vwap_seed_volume"))
    entry_session_low = _finite_positive(signal.get("entry_session_low_at_entry"))

    structural_families: list[tuple[str, float, float | None]] = []
    if structural_stop is not None:
        structural_families.append(("STRUCTURAL_BASE", structural_stop, None))
    if prior_day_low is not None:
        structural_families.append(("PRIOR_DAY_LOW", prior_day_low, None))
    if day0_support is not None:
        structural_families.append(("DAY0_SUPPORT", day0_support, None))
    if anchored_vwap is not None:
        structural_families.append(("ANCHORED_VWAP", anchored_vwap, None))
    if entry is not None and pre_entry_atr is not None:
        for multiple in ATR_MULTIPLES:
            atr_stop = entry - float(multiple) * pre_entry_atr
            if atr_stop > 0 and atr_stop < entry:
                structural_families.append(("ATR", float(atr_stop), float(multiple)))

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

        for stop_mode, stop_price, atr_multiple in structural_families:
            for target_r in R_TARGETS:
                rules.append(
                    SwingReplayRule(
                        stop_mode=stop_mode,
                        stop_price=stop_price,
                        atr_multiple=atr_multiple,
                        target_r_multiple=target_r,
                        max_hold_sessions=hold,
                        anchor_pv=anchor_pv,
                        anchor_volume=anchor_volume,
                        entry_session_low=entry_session_low,
                    )
                )

        # Dynamic exits are kept as distinct, target-free research families to
        # avoid an unnecessary Cartesian explosion with every target parameter.
        if prior_day_low is not None or structural_stop is not None:
            rules.append(
                SwingReplayRule(
                    stop_mode="PRIOR_DAY_LOW" if prior_day_low is not None else "STRUCTURAL_BASE",
                    stop_price=prior_day_low if prior_day_low is not None else structural_stop,
                    trailing_exit="PRIOR_DAY_LOW_BREAK",
                    max_hold_sessions=hold,
                    entry_session_low=entry_session_low,
                )
            )
        if structural_stop is not None:
            rules.append(
                SwingReplayRule(
                    stop_mode="STRUCTURAL_BASE",
                    stop_price=structural_stop,
                    trailing_exit="BASE_FAILURE",
                    max_hold_sessions=hold,
                    entry_session_low=entry_session_low,
                )
            )
            rules.append(
                SwingReplayRule(
                    stop_mode="STRUCTURAL_BASE",
                    stop_price=structural_stop,
                    trailing_exit="TRAILING_HIGHER_LOW",
                    max_hold_sessions=hold,
                    entry_session_low=entry_session_low,
                )
            )
        if anchored_vwap is not None:
            rules.append(
                SwingReplayRule(
                    stop_mode="ANCHORED_VWAP",
                    stop_price=anchored_vwap,
                    trailing_exit="ANCHORED_VWAP_LOSS",
                    max_hold_sessions=hold,
                    anchor_pv=anchor_pv,
                    anchor_volume=anchor_volume,
                    entry_session_low=entry_session_low,
                )
            )

    ids = [rule.rule_id for rule in rules]
    if len(ids) != len(set(ids)):
        raise RuntimeError("Dan swing replay grid contains duplicate rule identities")
    return rules
