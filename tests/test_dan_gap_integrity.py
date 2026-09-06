import pandas as pd

from scanner.core.multisession_replay import SwingReplayRule, simulate_multisession_trade
from scanner.strategies.dan_irish.research import overnight_gap_risk_summary, replay_dan_swing_signals


def _bars(rows):
    return pd.DataFrame([
        {
            "timestamp": pd.Timestamp(ts, tz="America/New_York").tz_convert("UTC"),
            "open": o,
            "high": h,
            "low": l,
            "close": c,
            "volume": 100,
            "vwap": c,
        }
        for ts, o, h, l, c in rows
    ])


def test_dynamic_trailing_gap_is_explicitly_marked_as_gap_through_stop():
    bars = _bars([
        ("2026-08-31 09:30", 10.0, 10.2, 9.8, 10.1),
        ("2026-08-31 15:59", 10.1, 10.3, 9.7, 10.2),
        ("2026-09-01 09:30", 9.0, 9.2, 8.9, 9.1),
        ("2026-09-01 15:59", 9.1, 9.2, 9.0, 9.1),
    ])
    result = simulate_multisession_trade(
        bars,
        entry_price=10.0,
        entry_timestamp=pd.Timestamp("2026-08-31 09:30", tz="America/New_York"),
        direction="LONG",
        rule=SwingReplayRule(
            stop_mode="STRUCTURAL_BASE",
            stop_price=8.5,
            trailing_exit="PRIOR_DAY_LOW_BREAK",
            max_hold_sessions=1,
        ),
        split_end_date="2026-09-01",
        available_end_date="2026-09-01",
    )
    assert result.exit_reason == "PRIOR_DAY_LOW_BREAK"
    assert bool(result.gap_through_stop)
    assert result.exit_price == 9.0


def test_overnight_gap_summary_counts_dynamic_gap_through_stops():
    replays = pd.DataFrame([{
        "strategy_id": "DAN_IRISH",
        "variant_id": "DAN_DAY2_CONTINUATION",
        "setup_id": "DAY2",
        "rule_id": "DAY2__TRAIL",
        "max_hold_sessions": 2,
        "split": "validation",
        "price_bucket": "5_10",
        "market_cap_bucket": "MICROCAP",
        "slippage_bps": 25.0,
        "selection_eligible_replay": True,
        "exit_reason": "PRIOR_DAY_LOW_BREAK",
        "gap_through_stop": True,
        "return_pct": -0.18,
    }])
    out = overnight_gap_risk_summary(replays)
    assert len(out) == 1
    assert int(out.iloc[0]["gap_stop_n"]) == 1
    assert float(out.iloc[0]["gap_stop_rate"]) == 1.0
    assert float(out.iloc[0]["worst_gap_stop_return"]) == -0.18


def test_missing_followup_minute_session_cannot_be_compressed_out_of_hold_horizon(tmp_path, monkeypatch):
    sessions = pd.bdate_range("2026-08-31", periods=3)
    daily = pd.DataFrame([
        {
            "symbol": "AAA",
            "timestamp": pd.Timestamp(f"{day.date()} 16:00", tz="America/New_York").tz_convert("UTC"),
            "open": 5.0,
            "high": 5.2,
            "low": 4.9,
            "close": 5.0,
            "volume": 1000,
            "vwap": 5.0,
        }
        for day in sessions
    ])

    missing_day = str(sessions[1].date())

    def minute_loader(root, namespace, day, feed, symbol):
        if str(day) == missing_day:
            return pd.DataFrame()
        return pd.DataFrame([{
            "symbol": symbol,
            "timestamp": pd.Timestamp(f"{day} 09:30", tz="America/New_York").tz_convert("UTC"),
            "open": 5.0,
            "high": 5.1,
            "low": 4.9,
            "close": 5.0,
            "volume": 100,
            "vwap": 5.0,
        }])

    monkeypatch.setattr(
        "scanner.strategies.dan_irish.research.default_dan_swing_rules",
        lambda signal: [
            SwingReplayRule(stop_pct=0.08, target_r_multiple=2.0, max_hold_sessions=1),
            SwingReplayRule(stop_pct=0.08, target_r_multiple=2.0, max_hold_sessions=2),
        ],
    )

    signals = pd.DataFrame([{
        "strategy_id": "DAN_IRISH",
        "variant_id": "DAN_OVERNIGHT_NEXT_OPEN",
        "setup_id": "OVERNIGHT_NEXT_OPEN",
        "symbol": "AAA",
        "date": str(sessions[0].date()),
        "direction": "LONG",
        "split": "validation",
        "entry_timestamp": pd.Timestamp(f"{sessions[0].date()} 09:30", tz="America/New_York"),
        "entry_price_raw": 5.0,
        "stop_reference": 4.6,
    }])

    replays, skips = replay_dan_swing_signals(
        tmp_path,
        "sip",
        signals,
        daily,
        {"validation": str(sessions[-1].date())},
        minute_loader,
        slippage_bps=(25.0,),
    )

    assert replays.empty
    assert not skips.empty
    assert set(skips["reason"]) == {"MISSING_DAN_SWING_SESSION_CACHE"}
    assert missing_day in set(skips["missing_session"])
