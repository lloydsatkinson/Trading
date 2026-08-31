import pandas as pd

from scanner.strategies.dan_irish.config import DanConfig
from scanner.strategies.dan_irish.intraday import generate_dan_intraday_signals


def bars(rows):
    return pd.DataFrame([
        {
            "symbol": "AAA",
            "timestamp": pd.Timestamp(ts, tz="America/New_York").tz_convert("UTC"),
            "open": o, "high": h, "low": l, "close": c, "volume": v, "vwap": vw,
        }
        for ts, o, h, l, c, v, vw in rows
    ])


def dan_context(**overrides):
    out = {
        "symbol": "AAA", "date": "2026-08-28", "prior_close": 4.0,
        "dan_candidate": True, "pm_gap_pct": 0.15,
        "pm_dollar_turnover": 5_000_000.0, "opening_rvol": 6.0,
        "market_cap": 200_000_000.0, "float_shares": 12_000_000.0,
        "catalyst_class": "NEWS", "split": "validation",
    }
    out.update(overrides)
    return out


def intraday_secondary_fixture():
    return bars([
        ("2026-08-28 09:30", 4.40, 4.85, 4.35, 4.75, 500, 4.65),
        ("2026-08-28 09:31", 4.72, 4.78, 4.65, 4.70, 100, 4.70),
        ("2026-08-28 09:32", 4.70, 4.75, 4.62, 4.68, 100, 4.68),
        ("2026-08-28 09:33", 4.68, 4.74, 4.64, 4.71, 100, 4.69),
        ("2026-08-28 09:34", 4.72, 4.82, 4.70, 4.80, 300, 4.76),
        ("2026-08-28 09:35", 4.81, 5.00, 4.79, 4.95, 400, 4.90),
    ])


def test_dan_intraday_waits_for_consolidation_break_and_enters_next_bar():
    fixture = intraday_secondary_fixture()
    out = generate_dan_intraday_signals(
        fixture,
        dan_context(),
        DanConfig(min_reference_extension_pct=0.20,
                  min_consolidation_minutes=3,
                  min_retained_gain=0.60,
                  min_breakout_volume_ratio=1.5),
    )
    row = out.iloc[0]
    assert row["strategy_id"] == "DAN_IRISH"
    assert row["variant_id"] == "DAN_INTRADAY_SECONDARY"
    assert str(row["signal_timestamp"])[11:16] == "09:34"
    assert str(row["entry_timestamp"])[11:16] == "09:35"
    assert row["entry_price_raw"] == fixture.iloc[5]["open"]
    assert row["stop_reference"] == row["base_low"] == 4.62
    assert row["price_bucket"] == "2_5"
    assert row["attribution"] == "DAN_DERIVED"
    assert row["_replay_mode"] == "intraday"
    assert row["setup_id"] == "C3_BASE_HIGH_V1P5"


def test_dan_intraday_emits_nothing_before_full_base_duration():
    out = generate_dan_intraday_signals(
        intraday_secondary_fixture(), dan_context(),
        DanConfig(min_reference_extension_pct=0.20,
                  min_consolidation_minutes=5,
                  min_retained_gain=0.60,
                  min_breakout_volume_ratio=1.5),
    )
    assert out.empty


def test_dan_intraday_rejects_excessive_giveback():
    fixture = intraday_secondary_fixture()
    fixture.loc[2, "low"] = 4.20
    fixture.loc[2, "close"] = 4.30
    out = generate_dan_intraday_signals(
        fixture, dan_context(),
        DanConfig(min_reference_extension_pct=0.20,
                  min_consolidation_minutes=3,
                  min_retained_gain=0.65,
                  min_breakout_volume_ratio=1.5),
    )
    assert out.empty
