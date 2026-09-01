from datetime import date

import numpy as np
import pandas as pd

from scanner.multistrategy.config import MultiStrategyConfig
from scanner.multistrategy.study import MultiStrategyStudy
from scanner.strategies.dan_irish.config import DanConfig
from scanner.strategies.dan_irish.corporate_actions import mark_corporate_action_replays
from scanner.strategies.dan_irish.swing import generate_dan_swing_signals


class _FakeBarsApi:
    def __init__(self):
        self.adjustments = []

    def stock_bars(self, symbols, timeframe, start, end, **kwargs):
        self.adjustments.append(kwargs.get("adjustment"))
        return pd.DataFrame()


def test_multistrategy_bar_fetches_pass_explicit_raw_adjustment(tmp_path):
    cfg = MultiStrategyConfig(bar_adjustment="raw")
    study = MultiStrategyStudy(root=tmp_path, feed="sip", sessions=1, cfg=cfg)
    fake = _FakeBarsApi()
    study._api = fake
    sessions = [date(2026, 8, 28)]

    study._daily_bars(["AAA"], sessions)
    study._fetch_early_day(["AAA"], sessions[0])
    study.ensure_minute_day(["AAA"], sessions[0])
    study._fetch_opening_history(["AAA"], sessions, sessions[0])

    assert fake.adjustments
    assert set(fake.adjustments) == {"raw"}


def _daily_fixture():
    rows = []
    for day in pd.bdate_range("2026-08-10", "2026-08-27"):
        rows.append((str(day.date()), 4.0, 4.2, 3.8, 4.0, 500_000, 4.0))
    rows.extend([
        ("2026-08-28", 4.40, 5.20, 4.30, 5.00, 2_000_000, 4.85),
        ("2026-08-31", 5.10, 5.35, 5.00, 5.25, 1_000_000, 5.18),
    ])
    return pd.DataFrame([
        {
            "symbol": "AAA",
            "timestamp": pd.Timestamp(f"{day} 16:00", tz="America/New_York").tz_convert("UTC"),
            "open": o,
            "high": h,
            "low": l,
            "close": c,
            "volume": v,
            "vwap": vw,
        }
        for day, o, h, l, c, v, vw in rows
    ])


def _minutes(day1_late_low=5.00):
    day0 = pd.DataFrame([
        {
            "symbol": "AAA",
            "timestamp": pd.Timestamp(ts, tz="America/New_York").tz_convert("UTC"),
            "open": o, "high": h, "low": l, "close": c, "volume": v, "vwap": vw,
        }
        for ts, o, h, l, c, v, vw in [
            ("2026-08-28 09:30", 4.40, 4.90, 4.35, 4.80, 1000, 4.70),
            ("2026-08-28 09:31", 4.80, 5.05, 4.75, 4.95, 800, 4.90),
            ("2026-08-28 15:59", 4.98, 5.02, 4.90, 5.00, 500, 4.96),
        ]
    ])
    day1 = pd.DataFrame([
        {
            "symbol": "AAA",
            "timestamp": pd.Timestamp(ts, tz="America/New_York").tz_convert("UTC"),
            "open": o, "high": h, "low": l, "close": c, "volume": v, "vwap": vw,
        }
        for ts, o, h, l, c, v, vw in [
            ("2026-08-31 08:00", 5.00, 5.08, 4.98, 5.05, 400, 5.03),
            ("2026-08-31 09:30", 5.10, 5.20, 5.00, 5.15, 600, 5.12),
            ("2026-08-31 15:59", 5.20, 5.30, day1_late_low, 5.25, 500, 5.20),
        ]
    ])
    return {date(2026, 8, 28): day0, date(2026, 8, 31): day1}


def _context():
    return {
        "symbol": "AAA",
        "date": "2026-08-28",
        "prior_close": 4.0,
        "dan_candidate": True,
        "pm_gap_pct": 0.20,
        "pm_dollar_turnover": 5_000_000.0,
        "opening_rvol": 6.0,
        "market_cap": 200_000_000.0,
        "float_shares": 12_000_000.0,
        "catalyst_class": "NEWS",
        "split": "validation",
    }


def _swing_from_minutes(minute_map):
    def loader(symbol, day):
        return minute_map.get(pd.Timestamp(day).date(), pd.DataFrame())

    out = generate_dan_swing_signals(
        _context(),
        _daily_fixture(),
        loader,
        DanConfig(min_consolidation_minutes=1),
    )
    return out[out["variant_id"].eq("DAN_OVERNIGHT_NEXT_OPEN")].iloc[0]


def test_next_open_swing_persists_only_pre_entry_dynamic_state():
    baseline = _swing_from_minutes(_minutes(day1_late_low=5.00))
    mutated_future = _swing_from_minutes(_minutes(day1_late_low=1.00))

    assert baseline["prior_day_low"] == 4.30
    assert baseline["day0_support"] == 4.30
    assert np.isfinite(float(baseline["pre_entry_atr"]))
    assert np.isfinite(float(baseline["anchored_vwap_at_entry"]))
    assert float(baseline["anchored_vwap_seed_volume"]) > 0
    assert baseline["anchored_vwap_at_entry"] == mutated_future["anchored_vwap_at_entry"]
    assert baseline["pre_entry_atr"] == mutated_future["pre_entry_atr"]
    assert baseline["prior_day_low"] == mutated_future["prior_day_low"]


def test_confirmed_split_marks_overlapping_swing_replay_ineligible():
    replays = pd.DataFrame([
        {
            "strategy_id": "DAN_IRISH",
            "symbol": "AAA",
            "entry_timestamp": pd.Timestamp("2026-08-28 15:30", tz="America/New_York"),
            "exit_timestamp": pd.Timestamp("2026-09-01 10:00", tz="America/New_York"),
            "selection_eligible_replay": True,
        },
        {
            "strategy_id": "DAN_IRISH",
            "symbol": "BBB",
            "entry_timestamp": pd.Timestamp("2026-08-28 15:30", tz="America/New_York"),
            "exit_timestamp": pd.Timestamp("2026-09-01 10:00", tz="America/New_York"),
            "selection_eligible_replay": True,
        },
    ])
    actions = pd.DataFrame([
        {
            "symbol": "AAA",
            "action_type": "reverse_split",
            "action_date": "2026-08-31",
        }
    ])

    out = mark_corporate_action_replays(replays, actions)
    aaa = out[out["symbol"].eq("AAA")].iloc[0]
    bbb = out[out["symbol"].eq("BBB")].iloc[0]
    assert bool(aaa["corporate_action_flag"]) is True
    assert bool(aaa["selection_eligible_replay"]) is False
    assert aaa["corporate_action_type"] == "reverse_split"
    assert bool(bbb["corporate_action_flag"]) is False
    assert bool(bbb["selection_eligible_replay"]) is True
