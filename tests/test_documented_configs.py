from scanner.core.replay import DEFAULT_SLIPPAGE_BPS
from scanner.core.rules import DEFAULT_R_TARGETS, MAX_HOLD_MINUTES


def test_documented_execution_grids_match_shared_config():
    assert DEFAULT_SLIPPAGE_BPS == (10, 25, 50, 75, 100)
    assert MAX_HOLD_MINUTES == (5, 10, 15, 30, 45, 60, 90, 120, 180, 240)
    assert DEFAULT_R_TARGETS == (1.0, 1.5, 2.0, 3.0, 4.0)
