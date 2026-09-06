import pandas as pd

from scanner.strategies.dan_irish.config import DanConfig
from scanner.strategies.dan_irish.swing import generate_dan_swing_signals


def bars(day, rows):
    return pd.DataFrame([
        {
            "symbol": "AAA",
            "timestamp": pd.Timestamp(f"{day} {hhmm}", tz="America/New_York").tz_convert("UTC"),
            "open": o, "high": h, "low": l, "close": c, "volume": v, "vwap": vw,
        }
        for hhmm, o, h, l, c, v, vw in rows
    ])


def daily_fixture():
    rows = [
        ("2026-08-28", 4.40, 6.00, 4.30, 5.50, 1_000_000, 5.20),
        ("2026-08-31", 5.50, 5.80, 5.30, 5.60, 500_000, 5.55),
        ("2026-09-01", 5.60, 5.90, 5.40, 5.70, 450_000, 5.65),
        ("2026-09-02", 5.70, 5.85, 5.50, 5.75, 400_000, 5.70),
        ("2026-09-03", 5.75, 6.10, 5.60, 6.00, 700_000, 5.92),
        ("2026-09-04", 6.00, 6.30, 5.90, 6.20, 750_000, 6.15),
    ]
    return pd.DataFrame([
        {
            "symbol": "AAA",
            "timestamp": pd.Timestamp(f"{day} 16:00", tz="America/New_York").tz_convert("UTC"),
            "open": o, "high": h, "low": l, "close": c, "volume": v, "vwap": vw,
        }
        for day, o, h, l, c, v, vw in rows
    ])


def day0_context():
    return {
        "symbol": "AAA", "date": "2026-08-28", "prior_close": 4.0,
        "dan_candidate": True, "market_cap": 200_000_000.0,
        "float_shares": 12_000_000.0, "pm_gap_pct": 0.20,
        "opening_rvol": 6.0, "catalyst_class": "NEWS", "split": "validation",
    }


def minute_map(late_day1_high=6.0):
    return {
        "2026-08-28": bars("2026-08-28", [
            ("15:30", 5.40, 5.52, 5.35, 5.50, 150, 5.35),
            ("15:31", 5.51, 5.58, 5.48, 5.56, 180, 5.38),
            ("16:01", 5.58, 6.05, 5.57, 6.02, 300, 5.60),
            ("16:02", 6.03, 6.10, 6.00, 6.08, 250, 5.70),
        ]),
        "2026-08-31": bars("2026-08-31", [
            ("09:30", 5.50, 5.55, 5.45, 5.50, 100, 5.50),
            ("09:31", 5.50, 5.56, 5.46, 5.52, 100, 5.51),
            ("09:32", 5.52, 5.57, 5.48, 5.54, 100, 5.52),
            ("09:33", 5.55, 5.62, 5.53, 5.60, 250, 5.55),
            ("09:34", 5.61, 5.70, 5.58, 5.68, 200, 5.60),
            ("15:59", 5.70, late_day1_high, 5.65, 5.75, 200, 5.68),
        ]),
        "2026-09-01": bars("2026-09-01", [
            ("09:30", 5.62, 5.70, 5.58, 5.66, 100, 5.64),
            ("09:31", 5.66, 5.72, 5.62, 5.68, 100, 5.66),
            ("09:32", 5.68, 5.74, 5.65, 5.72, 100, 5.68),
            ("09:33", 5.75, 5.90, 5.73, 5.86, 250, 5.76),
            ("09:34", 5.87, 5.95, 5.84, 5.92, 200, 5.82),
        ]),
        "2026-09-02": bars("2026-09-02", [
            ("09:30", 5.72, 5.78, 5.68, 5.74, 100, 5.72),
            ("09:31", 5.74, 5.80, 5.70, 5.76, 100, 5.74),
            ("09:32", 5.76, 5.82, 5.72, 5.78, 100, 5.75),
            ("09:33", 5.90, 6.00, 5.88, 5.96, 250, 5.84),
            ("09:34", 5.97, 6.05, 5.94, 6.02, 200, 5.90),
        ]),
        "2026-09-03": bars("2026-09-03", [
            ("09:30", 5.80, 5.84, 5.75, 5.80, 100, 5.79),
            ("09:31", 5.80, 5.85, 5.76, 5.82, 100, 5.80),
            ("09:32", 5.82, 5.86, 5.78, 5.83, 100, 5.81),
            ("09:33", 5.92, 6.02, 5.90, 6.00, 250, 5.88),
            ("09:34", 6.01, 6.10, 5.98, 6.08, 200, 5.95),
        ]),
        "2026-09-04": bars("2026-09-04", [
            ("09:30", 6.02, 6.08, 5.98, 6.04, 100, 6.02),
            ("09:31", 6.04, 6.10, 6.00, 6.06, 100, 6.04),
            ("09:32", 6.06, 6.12, 6.02, 6.08, 100, 6.05),
            ("09:33", 6.15, 6.25, 6.12, 6.22, 250, 6.12),
            ("09:34", 6.23, 6.32, 6.20, 6.30, 200, 6.18),
        ]),
    }


def loader_from(mapping):
    def load(symbol, day):
        return mapping.get(str(day), pd.DataFrame()).copy()
    return load


def test_overnight_next_open_uses_day0_signal_and_next_session_open_entry():
    out = generate_dan_swing_signals(day0_context(), daily_fixture(), loader_from(minute_map()), DanConfig(min_consolidation_minutes=3))
    row = out[out["variant_id"].eq("DAN_OVERNIGHT_NEXT_OPEN")].iloc[0]
    assert row["signal_timestamp"].date().isoformat() == "2026-08-28"
    assert str(row["entry_timestamp"])[0:10] == "2026-08-31"
    assert row["entry_price_raw"] == 5.50
    assert row["attribution"] == "DAN_INSPIRED"
    assert row["_replay_mode"] == "swing"


def test_day2_signal_does_not_use_later_day2_high_to_set_base():
    normal = generate_dan_swing_signals(day0_context(), daily_fixture(), loader_from(minute_map(6.0)), DanConfig(min_consolidation_minutes=3))
    spiked = generate_dan_swing_signals(day0_context(), daily_fixture(), loader_from(minute_map(99.0)), DanConfig(min_consolidation_minutes=3))
    a = normal[normal["variant_id"].eq("DAN_DAY2_CONTINUATION")].iloc[0]
    b = spiked[spiked["variant_id"].eq("DAN_DAY2_CONTINUATION")].iloc[0]
    assert a["signal_timestamp"] == b["signal_timestamp"]
    assert a["base_high"] == b["base_high"]


def test_multiday_compression_base_lengths_are_separate_setup_identities():
    out = generate_dan_swing_signals(day0_context(), daily_fixture(), loader_from(minute_map()), DanConfig(min_consolidation_minutes=3))
    compression = out[out["variant_id"].eq("DAN_MULTIDAY_COMPRESSION")]
    assert {1, 2, 3}.issubset(set(compression["base_length_sessions"]))
    assert compression["setup_id"].nunique() == len(compression)
