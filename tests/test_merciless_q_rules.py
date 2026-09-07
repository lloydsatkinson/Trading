from scanner.core.rules import default_rules_for_signal, merciless_rules_for_signal


def test_merciless_rules_are_structural_and_focused():
    signal = {
        "strategy_id": "MERCILESS_Q",
        "stop_reference": 4.50,
    }
    rules = merciless_rules_for_signal(signal)

    assert len(rules) == 35
    assert all(rule.stop_price == 4.50 for rule in rules)
    assert all(rule.stop_pct is None for rule in rules)
    assert all(rule.target_r_multiple is not None for rule in rules)
    assert {rule.target_r_multiple for rule in rules} == {0.5, 1.0, 1.5, 2.0, 3.0}
    assert {rule.max_hold_minutes for rule in rules if not rule.hold_to_eod} == {5, 10, 15, 30, 45, 60}
    assert sum(rule.hold_to_eod for rule in rules) == 5


def test_default_rule_selector_uses_focused_grid_for_merciless_only():
    merciless = default_rules_for_signal({
        "strategy_id": "MERCILESS_Q",
        "stop_reference": 4.50,
    })
    ordinary = default_rules_for_signal({
        "strategy_id": "ORB",
        "stop_reference": 4.50,
    })

    assert len(merciless) == 35
    assert len(ordinary) > len(merciless)
