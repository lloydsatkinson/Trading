from scripts.run_target_sweep import target_from_structural_risk


def test_target_from_structural_risk_long():
    assert target_from_structural_risk(side="LONG", entry=10.0, original_stop=9.5, target_r=3.0) == 11.5


def test_target_from_structural_risk_short():
    assert target_from_structural_risk(side="SHORT", entry=10.0, original_stop=10.5, target_r=3.0) == 8.5
