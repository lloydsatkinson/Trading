import math

from scanner.core.models import SignalRecord, market_cap_bucket, market_cap_in_primary_universe


def test_primary_universe_bounds():
    assert market_cap_in_primary_universe(50_000_000) is True
    assert market_cap_in_primary_universe(299_999_999) is True
    assert market_cap_in_primary_universe(300_000_000) is True
    assert market_cap_in_primary_universe(1_999_999_999) is True
    assert market_cap_in_primary_universe(49_999_999) is False
    assert market_cap_in_primary_universe(2_000_000_000) is False
    assert market_cap_in_primary_universe(float("nan")) is False
    assert market_cap_in_primary_universe(None) is False


def test_market_cap_bucket_uses_research_boundaries():
    assert market_cap_bucket(49_999_999) == "BELOW_MICROCAP"
    assert market_cap_bucket(50_000_000) == "MICROCAP"
    assert market_cap_bucket(299_999_999) == "MICROCAP"
    assert market_cap_bucket(300_000_000) == "SMALL_CAP"
    assert market_cap_bucket(1_999_999_999) == "SMALL_CAP"
    assert market_cap_bucket(2_000_000_000) == "LARGER"
    assert market_cap_bucket(math.nan) == "UNKNOWN"


def test_signal_record_emits_common_strategy_fields_and_unknown_defaults():
    signal = SignalRecord(
        strategy_id="ORB",
        variant_id="ORB_LONG_BREAK",
        symbol="AAA",
        date="2026-08-28",
        direction="LONG",
        signal_timestamp="2026-08-28 09:36:00-04:00",
        reference_price=5.0,
        entry_timestamp="2026-08-28 09:37:00-04:00",
        entry_price_raw=5.05,
        entry_price_slipped=5.062625,
        stop_reference=4.8,
    )
    out = signal.to_dict()
    assert out["strategy_id"] == "ORB"
    assert out["direction"] == "LONG"
    assert out["market_cap_bucket"] == "UNKNOWN"
    assert out["float_bucket"] == "UNKNOWN"
    assert out["gap_bucket"] == "UNKNOWN"
    assert out["rvol_bucket"] == "UNKNOWN"
    assert out["time_of_day_bucket"] == "UNKNOWN"
    assert out["catalyst_class"] == "UNKNOWN"
    assert out["borrow_status"] == "UNKNOWN"
