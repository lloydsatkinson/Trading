import pandas as pd
import pytest

from scanner.strategies.merciless_q.reporting import (
    friction_threshold_summary,
    sequence_bucket_summary,
)


def _selected_rules():
    return pd.DataFrame([{
        "strategy_id": "MERCILESS_Q",
        "variant_id": "MMQ_FIRST_PULLBACK",
        "direction": "LONG",
        "rule_id": "SSTRUCT_R1_H15",
    }])


def _replays():
    rows = []
    baseline = [
        ("2026-08-21", 1, 0.03, 0.05, 4.0),
        ("2026-08-22", 1, -0.01, 0.02, 7.0),
        ("2026-08-23", 2, 0.02, 0.04, 6.0),
        ("2026-08-24", 2, -0.02, 0.01, 9.0),
        ("2026-08-25", 5, 0.04, 0.08, 5.0),
        ("2026-08-26", 6, -0.01, 0.02, 11.0),
    ]
    for day, sequence, ret, peak, minutes in baseline:
        rows.append({
            "strategy_id": "MERCILESS_Q",
            "variant_id": "MMQ_FIRST_PULLBACK",
            "direction": "LONG",
            "split": "validation",
            "rule_id": "SSTRUCT_R1_H15",
            "sequence_number": sequence,
            "slippage_bps": 25.0,
            "return_pct": ret,
            "peak_return_pct": peak,
            "minutes_to_peak": minutes,
            "date": day,
            "entry_timestamp": f"{day} 09:40:00-04:00",
        })

    curves = {
        10.0: [0.03, -0.01],
        50.0: [0.01, -0.015],
        75.0: [-0.01, -0.02],
        100.0: [-0.02, -0.03],
    }
    for bps, returns in curves.items():
        for i, ret in enumerate(returns, start=1):
            day = f"2026-08-{20 + i:02d}"
            rows.append({
                "strategy_id": "MERCILESS_Q",
                "variant_id": "MMQ_FIRST_PULLBACK",
                "direction": "LONG",
                "split": "validation",
                "rule_id": "SSTRUCT_R1_H15",
                "sequence_number": i,
                "slippage_bps": bps,
                "return_pct": ret,
                "peak_return_pct": 0.04,
                "minutes_to_peak": 5.0,
                "date": day,
                "entry_timestamp": f"{day} 09:40:00-04:00",
            })
    return pd.DataFrame(rows)


def test_sequence_bucket_summary_matches_design_buckets_and_peak_metrics():
    out = sequence_bucket_summary(_replays(), _selected_rules(), baseline_slippage_bps=25.0)

    assert set(out["sequence_bucket"]) == {"1", "2", "5+"}
    first = out[out["sequence_bucket"].eq("1")].iloc[0]
    late = out[out["sequence_bucket"].eq("5+")].iloc[0]
    assert first["n"] == 2
    assert first["expectancy"] == pytest.approx(0.01)
    assert first["profit_factor"] == pytest.approx(3.0)
    assert first["median_peak_return_pct"] == pytest.approx(0.035)
    assert first["median_minutes_to_peak"] == pytest.approx(5.5)
    assert late["n"] == 2
    assert late["expectancy"] == pytest.approx(0.015)


def test_friction_threshold_summary_uses_validation_selected_rule_only():
    out = friction_threshold_summary(_replays(), _selected_rules())
    row = out.iloc[0]

    assert row["selected_rule_id"] == "SSTRUCT_R1_H15"
    assert row["last_pf_ge_1_0_bps"] == 25.0
    assert row["last_pf_ge_1_25_bps"] == 25.0
    assert row["last_positive_expectancy_bps"] == 25.0
