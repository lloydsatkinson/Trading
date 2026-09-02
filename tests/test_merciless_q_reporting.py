import pandas as pd
import pytest

from scanner.strategies.merciless_q.reporting import friction_break_even, summarize_sequence_edge


def _replays():
    rows = []
    returns = {
        1: {
            10.0: [0.03, 0.01],
            25.0: [0.0266666667, -0.0066666667],
            50.0: [0.00, -0.01],
        },
        2: {
            10.0: [0.02, -0.01],
            25.0: [0.02, -0.03],
            50.0: [0.00, -0.04],
        },
    }
    for sequence_number, by_bps in returns.items():
        for bps, values in by_bps.items():
            for day_idx, value in enumerate(values, start=1):
                rows.append({
                    "strategy_id": "MERCILESS_Q",
                    "variant_id": "MMQ_FIRST_PULLBACK",
                    "direction": "LONG",
                    "split": "validation",
                    "rule_id": "SSTRUCT_R2_H15",
                    "sequence_number": sequence_number,
                    "slippage_bps": bps,
                    "return_pct": value,
                    "date": f"2026-08-{20 + day_idx:02d}",
                })
    return pd.DataFrame(rows)


def test_sequence_edge_is_measured_separately_at_baseline_friction():
    out = summarize_sequence_edge(_replays(), baseline_slippage_bps=25.0)
    first = out[out["sequence_number"].eq(1)].iloc[0]
    second = out[out["sequence_number"].eq(2)].iloc[0]

    assert first["n"] == 2
    assert first["expectancy"] == pytest.approx(0.01)
    assert first["profit_factor"] == pytest.approx(4.0)
    assert second["expectancy"] == pytest.approx(-0.005)
    assert second["profit_factor"] == pytest.approx(2.0 / 3.0)


def test_friction_break_even_interpolates_expectancy_crossing():
    out = friction_break_even(_replays())
    first = out[out["sequence_number"].eq(1)].iloc[0]

    assert first["last_positive_grid_bps"] == 25.0
    assert first["first_nonpositive_grid_bps"] == 50.0
    assert first["break_even_bps"] == pytest.approx(41.6666667)
    assert first["expectancy_at_low_bps"] == pytest.approx(0.01)
    assert first["expectancy_at_high_bps"] == pytest.approx(-0.005)
