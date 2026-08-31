from datetime import date

import numpy as np
import pandas as pd

from scanner.multistrategy.study import MultiStrategyStudy
from scanner.strategies.dan_irish.config import DanConfig
from scanner.strategies.dan_irish.intraday import generate_dan_intraday_signals
from scanner.strategies.dan_irish.research import overnight_gap_risk_summary
from scanner.strategies.dan_irish.swing import generate_dan_swing_signals


def _bars(rows, symbol="AAA"):
    return pd.DataFrame([
        {
            "symbol": symbol,
            "timestamp": pd.Timestamp(ts, tz="America/New_York").tz_convert("UTC"),
            "open": o,
            "high": h,
            "low": l,
            "close": c,
            "volume": v,
            "vwap": vw,
        }
        for ts, o, h, l, c, v, vw in rows
    ])


def _intraday_fixture():
    return _bars([
        ("2026-08-28 09:30", 4.40, 4.85, 4.35, 4.75, 500, 4.65),
        ("2026-08-28 09:31", 4.72, 4.78, 4.65, 4.70, 100, 4.70),
        ("2026-08-28 09:32", 4.70, 4.75, 4.62, 4.68, 100, 4.68),
        ("2026-08-28 09:33", 4.68, 4.74, 4.64, 4.71, 100, 4.69),
        ("2026-08-28 09:34", 4.72, 4.82, 4.70, 4.80, 300, 4.76),
        ("2026-08-28 09:35", 4.81, 5.00, 4.79, 4.95, 400, 4.90),
    ])


def _intraday_context():
    return {
        "symbol": "AAA",
        "date": "2026-08-28",
        "prior_close": 0.80,
        "dan_candidate": True,
        "pm_gap_pct": 4.5,
        "pm_dollar_turnover": 5_000_000.0,
        "opening_rvol": 6.0,
        "market_cap": 200_000_000.0,
        "float_shares": 12_000_000.0,
        "catalyst_class": "NEWS",
        "split": "development",
    }


def _swing_daily():
    return pd.DataFrame([
        {
            "symbol": "AAA",
            "timestamp": pd.Timestamp("2026-08-28 16:00", tz="America/New_York").tz_convert("UTC"),
            "open": 1.00,
            "high": 1.60,
            "low": 0.95,
            "close": 1.40,
            "volume": 2_000_000,
            "vwap": 1.30,
        },
        {
            "symbol": "AAA",
            "timestamp": pd.Timestamp("2026-08-31 16:00", tz="America/New_York").tz_convert("UTC"),
            "open": 1.45,
            "high": 1.75,
            "low": 1.38,
            "close": 1.65,
            "volume": 1_000_000,
            "vwap": 1.58,
        },
    ])


def _swing_context():
    return {
        "symbol": "AAA",
        "date": "2026-08-28",
        "prior_close": 0.80,
        "dan_candidate": True,
        "market_cap": 200_000_000.0,
        "float_shares": 12_000_000.0,
        "pm_gap_pct": 0.50,
        "opening_rvol": 6.0,
        "catalyst_class": "NEWS",
        "split": "development",
    }


def _swing_minutes(symbol, day):
    if str(day) != "2026-08-31":
        return pd.DataFrame()
    return _bars([
        ("2026-08-31 09:30", 1.45, 1.50, 1.40, 1.45, 100, 1.45),
        ("2026-08-31 09:31", 1.45, 1.50, 1.42, 1.46, 100, 1.46),
        ("2026-08-31 09:32", 1.51, 1.58, 1.49, 1.55, 250, 1.52),
        ("2026-08-31 09:33", 1.56, 1.65, 1.54, 1.62, 200, 1.58),
    ], symbol=symbol)


def test_intraday_price_bucket_uses_entry_price_not_prior_close():
    out = generate_dan_intraday_signals(
        _intraday_fixture(),
        _intraday_context(),
        DanConfig(
            min_reference_extension_pct=0.20,
            min_consolidation_minutes=3,
            min_retained_gain=0.60,
            min_breakout_volume_ratio=1.5,
        ),
    )
    assert not out.empty
    row = out.iloc[0]
    assert row["entry_price_raw"] == 4.81
    assert row["price_bucket"] == "2_5"


def test_swing_price_bucket_uses_entry_price_not_prior_close():
    out = generate_dan_swing_signals(
        _swing_context(),
        _swing_daily(),
        _swing_minutes,
        DanConfig(min_consolidation_minutes=2),
    )
    row = out[out["variant_id"].eq("DAN_OVERNIGHT_NEXT_OPEN")].iloc[0]
    assert row["entry_price_raw"] == 1.45
    assert row["price_bucket"] == "1_2"


def test_later_session_swing_signal_uses_its_actual_chronological_split():
    session_splits = {
        "2026-08-28": "development",
        "2026-08-31": "validation",
    }
    out = generate_dan_swing_signals(
        _swing_context(),
        _swing_daily(),
        _swing_minutes,
        DanConfig(min_consolidation_minutes=2),
        session_splits=session_splits,
    )
    overnight = out[out["variant_id"].eq("DAN_OVERNIGHT_NEXT_OPEN")].iloc[0]
    day2 = out[out["variant_id"].eq("DAN_DAY2_CONTINUATION")].iloc[0]
    assert overnight["split"] == "development"
    assert day2["split"] == "validation"


def test_native_study_exposes_session_split_map(tmp_path, monkeypatch):
    study = MultiStrategyStudy(root=tmp_path, feed="sip", sessions=1)
    session = date(2026, 8, 28)
    monkeypatch.setattr(study, "_completed_sessions", lambda: [session])
    monkeypatch.setattr(study, "_assets", lambda: pd.DataFrame({"symbol": []}))
    monkeypatch.setattr(study, "_daily_bars", lambda symbols, sessions: pd.DataFrame())
    monkeypatch.setattr(study, "_prior_close_map", lambda daily: {})
    monkeypatch.setattr(study, "_fetch_early_day", lambda symbols, day: pd.DataFrame())

    meta = study.run(include_dan_candidates=True)
    assert meta["session_splits"] == {"2026-08-28": "development"}


def test_overnight_gap_risk_keeps_setup_and_exit_rule_identity_separate():
    base = {
        "strategy_id": "DAN_IRISH",
        "variant_id": "DAN_OVERNIGHT_NEXT_OPEN",
        "setup_id": "OVERNIGHT_NEXT_OPEN",
        "split": "validation",
        "price_bucket": "1_2",
        "market_cap_bucket": "MICROCAP",
        "slippage_bps": 25.0,
        "selection_eligible_replay": True,
    }
    x = pd.DataFrame([
        {**base, "rule_id": "S08_T20_NONE_HS1", "max_hold_sessions": 1, "exit_reason": "GAP_STOP", "return_pct": -0.25},
        {**base, "rule_id": "S08_T20_NONE_HS1", "max_hold_sessions": 1, "exit_reason": "TARGET", "return_pct": 0.20},
        {**base, "rule_id": "S15_T30_NONE_HS2", "max_hold_sessions": 2, "exit_reason": "TARGET", "return_pct": 0.30},
        {**base, "rule_id": "S15_T30_NONE_HS2", "max_hold_sessions": 2, "exit_reason": "TIME", "return_pct": 0.05},
    ])
    out = overnight_gap_risk_summary(x)
    assert len(out) == 2
    assert set(out["rule_id"]) == {"S08_T20_NONE_HS1", "S15_T30_NONE_HS2"}
    rates = dict(zip(out["rule_id"], out["gap_stop_rate"]))
    assert np.isclose(rates["S08_T20_NONE_HS1"], 0.5)
    assert np.isclose(rates["S15_T30_NONE_HS2"], 0.0)
