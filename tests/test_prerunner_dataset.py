from datetime import date

from trading_lab.prerunner_dataset import eligible_symbol_map, standardize_api_bars


def test_standardize_api_bars_attaches_point_in_time_context():
    raw = {
        "AAA": [{"t": "2026-08-10T13:30:00Z", "o": 2.0, "h": 2.1, "l": 1.9, "c": 2.05, "v": 12345}]
    }
    ctx = {
        ("AAA", date(2026, 8, 10)): {
            "previous_close": 1.8,
            "prior20_median_volume": 400_000,
            "prior20_max_volume": 900_000,
            "prior4d_return": 0.12,
        }
    }
    out = standardize_api_bars(raw, date(2026, 8, 10), ctx)
    assert len(out) == 1
    row = out.iloc[0]
    assert row.ticker == "AAA"
    assert row.previous_close == 1.8
    assert row.prior20_median_volume == 400_000
    assert row.volume == 12345


def test_eligible_symbol_map_uses_prior_price_and_volume_only():
    d = date(2026, 8, 10)
    ctx = {
        ("A", d): {"previous_close": 2.0, "prior20_median_volume": 100_000, "high": 20.0, "low": 0.5},
        ("B", d): {"previous_close": 0.50, "prior20_median_volume": 1_000_000, "high": 50.0, "low": 0.1},
        ("C", d): {"previous_close": 3.0, "prior20_median_volume": 10_000, "high": 30.0, "low": 0.2},
    }
    out = eligible_symbol_map(ctx, [d], min_price=0.75, max_price=20.0, min_prior_volume=50_000)
    assert out[d] == ["A"]
