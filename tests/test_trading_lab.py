import math
import pandas as pd

from trading_lab.features import add_signal_time_features
from trading_lab.metrics import evaluate_returns
from trading_lab.presets import candidate_strategies
from trading_lab.rules import RangeRule
from trading_lab.splits import apply_standard_splits
from trading_lab.tournament import TournamentConfig, evaluate_frozen_candidate, rank_candidates


def test_prior4d_is_signal_time_feature():
    out = add_signal_time_features(pd.DataFrame({"move_1d": [0.10], "move_5d": [0.331]}))
    assert math.isclose(out.loc[0, "prior4d"], 1.331 / 1.10 - 1.0, rel_tol=1e-12)


def test_costs_are_applied_before_profit_factor():
    m = evaluate_returns(pd.Series([0.05, -0.02, 0.03, -0.01]), 0.005, 4)
    assert math.isclose(m.expectancy, 0.0075, rel_tol=1e-12)
    assert math.isclose(m.profit_factor, 1.75, rel_tol=1e-12)
    assert m.trades_per_day == 1.0


def test_rule_filters_are_deterministic():
    frame = pd.DataFrame({"move_1d":[.06,.06],"prior4d":[.03,.03],"rvol":[5.,5.],"price":[.9,1.],"dollar_volume":[2e6,2e6],"daily_rank":[10,10],"fresh_sec_3d":[1,1]})
    rule = RangeRule(name="r", move_1d=(.05,.15), min_price=1, max_price=20, min_dollar_volume=1e6, max_daily_rank=25, require_fresh_sec_days=3)
    assert rule.mask(frame).tolist() == [False, True]


def test_standard_splits_isolate_july_final():
    frame = pd.DataFrame({"date": pd.to_datetime(["2025-12-31","2026-01-02","2026-05-01","2026-07-01","2026-08-01"])})
    assert apply_standard_splits(frame)["split"].tolist() == ["dev","val","hold","final","other"]


def _sample():
    rows=[]
    for split, dates, vals in [("dev",["2025-01-02","2025-01-03","2025-01-06"],[.04,.03,-.01]),("val",["2026-01-02","2026-01-05"],[.03,-.01]),("hold",["2026-05-01","2026-05-04"],[.02,-.005]),("final",["2026-07-01","2026-07-02"],[-.04,-.03])]:
        for date,ret in zip(dates,vals):
            rows.append({"date":pd.Timestamp(date),"move_1d":.06,"move_5d":.10,"prior4d":.037,"rvol":25.,"price":5.,"return_1d":ret,"split":split})
    return pd.DataFrame(rows)


def test_candidate_ranking_never_uses_final():
    frame=_sample(); rule=RangeRule(name="candidate", move_1d=(.05,.15), rvol=(20,50), max_price=20)
    ranked=rank_candidates(frame,[rule],TournamentConfig(roundtrip_cost=.005,minimum_n={"dev":3,"val":2,"hold":2}))
    assert len(ranked)==1
    assert not any(c.startswith("final_") for c in ranked.columns)


def test_final_collapse_is_rejected():
    frame=_sample(); rule=RangeRule(name="candidate", move_1d=(.05,.15), rvol=(20,50), max_price=20)
    result=evaluate_frozen_candidate(frame,rule,roundtrip_cost=.005,minimum_final_n=2,min_final_pf=1.3)
    assert not result.accepted
    assert result.reason == "FINAL_EXPECTANCY_NON_POSITIVE"


def test_early_runner_preset_is_frozen():
    rules={r.name:r for r in candidate_strategies()}
    r=rules["CATALYST_EARLY_RUNNER"]
    assert (r.min_price,r.max_price,r.move_1d,r.rvol,r.max_daily_rank,r.require_fresh_sec_days)==(1.0,20.0,(.05,.15),(2.0,10.0),25,3)
