from scanner.core.rules import common_percentage_rules, structural_r_rules, rule_family_id, MAX_HOLD_MINUTES
from scanner.core.replay import ReplayRule


def test_max_hold_grid_extends_to_240_minutes():
    assert MAX_HOLD_MINUTES == (5, 10, 15, 30, 45, 60, 90, 120, 180, 240)


def test_percentage_grid_has_eod_rules():
    rules = common_percentage_rules(stop_pcts=(0.05,), target_pcts=(0.10,), hold_minutes=(5, 240), include_eod=True)
    assert [r.max_hold_minutes for r in rules if not r.hold_to_eod] == [5, 240]
    assert any(r.hold_to_eod for r in rules)


def test_structural_r_rules_use_signal_stop_reference():
    signal = {"stop_reference": 9.5}
    rules = structural_r_rules(signal, r_targets=(1.0, 2.0), hold_minutes=(30,), include_eod=False)
    assert [(r.stop_price, r.target_r_multiple, r.max_hold_minutes) for r in rules] == [
        (9.5, 1.0, 30),
        (9.5, 2.0, 30),
    ]


def test_structural_rule_family_id_does_not_fragment_by_actual_stop_price():
    a = ReplayRule(stop_price=9.5, target_r_multiple=2.0, max_hold_minutes=60)
    b = ReplayRule(stop_price=4.2, target_r_multiple=2.0, max_hold_minutes=60)
    assert rule_family_id(a) == rule_family_id(b) == "SSTRUCT_R2_H60"
