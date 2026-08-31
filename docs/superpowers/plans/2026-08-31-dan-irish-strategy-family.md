# Dan Irish Strategy Family Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Dan Irish intraday secondary-expansion and Dan-inspired overnight/Day-2/multi-day swing continuation research to the existing Trading Research Lab while preserving the locked ORB, VWAP and SerClick behaviour.

**Architecture:** Reuse `MultiStrategyStudy`, the existing Alpaca client/cache, common signal schema, intraday replay, reporting and validation/ranking stack. Add a separate Dan candidate frame so Dan's broad price universe never widens ORB/VWAP inputs, add focused Dan feature/signal modules, and add a dedicated multi-session replay path for overnight and swing trades. The runner combines intraday and swing replay rows into the same reporting/ranking pipeline while censoring any swing horizon that crosses a validation split boundary or runs beyond available future data.

**Tech Stack:** Python 3.12, pandas >=2.1, numpy >=1.26, requests >=2.31, python-dotenv >=1.0, tabulate >=0.9, pytest >=8.0, GitHub Actions, existing Alpaca SIP/IEX REST client.

**Spec:** `docs/superpowers/specs/2026-08-31-dan-irish-strategy-family-design.md`

## Global Constraints

- Research/backtest/paper validation only; no live order routing.
- Preserve existing `MultiStrategyConfig.min_price=1.0` and `max_price=30.0` for ORB/VWAP.
- Preserve frozen SerClick historical baseline ending `2026-08-27`; forward SerClick begins `2026-08-28`.
- Dan price buckets are `LT_1`, `1_2`, `2_5`, `5_10`, `10_20`, `20_50`, `50_100`, `GE_100`.
- Intraday Dan entries use completed signal bars and the next executable one-minute bar only.
- Intraday slippage scenarios remain 10, 25, 50, 75 and 100 bps.
- Swing stop gaps use the first executable observed price after the stop is violated; never assume a stop-price fill through an overnight gap.
- Swing maximum holds are 1, 2, 3, 4, 5, 7 and 10 subsequent regular-session closes after entry.
- Development -> validation -> locked test -> forward order is immutable. Test/forward outcomes never select rules.
- A swing rule whose requested horizon crosses into a later split is `boundary_censored=true` and excluded from selection metrics.
- A swing rule without enough future data is `right_censored=true` and excluded from complete-horizon metrics.
- Existing strategy ranking remains validation-led at 25 bps and retains the current 10% production expectancy hurdle.
- Missing market cap, float, news, halt or catalyst history remains explicit `UNKNOWN`; future snapshots are never backfilled.
- Existing ORB/VWAP/SerClick API-free integration tests must remain unchanged and passing.

---

### Task 1: Canonical Dan price and retained-gain features

**Files:**
- Modify: `scanner/core/models.py`
- Create: `scanner/strategies/dan_irish/__init__.py`
- Create: `scanner/strategies/dan_irish/config.py`
- Create: `scanner/strategies/dan_irish/features.py`
- Create: `tests/test_dan_features.py`

**Interfaces:**
- Produces `price_bucket(value: Any) -> str` in `scanner.core.models`.
- Produces `retained_gain_ratio(impulse_start: Any, impulse_high: Any, reference_price: Any) -> float`.
- Produces `bucket_retained_gain(value: Any) -> str`.
- Produces immutable `DanConfig` and research grids used by later tasks.

- [ ] **Step 1: Write failing price-bucket boundary tests.**

```python
from scanner.core.models import price_bucket


def test_dan_price_bucket_boundaries():
    assert price_bucket(0.99) == "LT_1"
    assert price_bucket(1.00) == "1_2"
    assert price_bucket(1.99) == "1_2"
    assert price_bucket(2.00) == "2_5"
    assert price_bucket(5.00) == "5_10"
    assert price_bucket(10.00) == "10_20"
    assert price_bucket(20.00) == "20_50"
    assert price_bucket(50.00) == "50_100"
    assert price_bucket(100.00) == "GE_100"
    assert price_bucket(None) == "UNKNOWN"
```

- [ ] **Step 2: Run the test and verify RED.**

Run: `PYTHONPATH=. pytest tests/test_dan_features.py::test_dan_price_bucket_boundaries -q`

Expected: FAIL because `price_bucket` does not exist.

- [ ] **Step 3: Implement `price_bucket` without changing market-cap helpers.**

```python
def price_bucket(value: Any) -> str:
    price = _finite_number(value)
    if price is None or price <= 0:
        return "UNKNOWN"
    if price < 1:
        return "LT_1"
    if price < 2:
        return "1_2"
    if price < 5:
        return "2_5"
    if price < 10:
        return "5_10"
    if price < 20:
        return "10_20"
    if price < 50:
        return "20_50"
    if price < 100:
        return "50_100"
    return "GE_100"
```

- [ ] **Step 4: Add failing retained-gain tests.**

```python
import numpy as np
from scanner.strategies.dan_irish.features import retained_gain_ratio


def test_retained_gain_ratio_and_invalid_denominator():
    assert retained_gain_ratio(2.0, 6.0, 5.0) == 0.75
    assert retained_gain_ratio(4.0, 4.0, 4.0) != retained_gain_ratio(4.0, 4.0, 4.0)  # NaN
    assert np.isnan(retained_gain_ratio(None, 6.0, 5.0))
```

- [ ] **Step 5: Run and verify RED, then implement feature helpers and config.**

```python
from __future__ import annotations
from dataclasses import dataclass
from math import isfinite
from typing import Any
import numpy as np

IMPULSE_GRID = (0.15, 0.20, 0.30, 0.50, 0.75)
TURNOVER_GRID = (1_000_000.0, 3_000_000.0, 5_000_000.0, 10_000_000.0)
RETAINED_GAIN_GRID = (0.40, 0.50, 0.65, 0.80)
CONSOLIDATION_MINUTES_GRID = (10, 20, 30, 45, 60, 90)
PULLBACK_DEPTH_GRID = (0.10, 0.20, 0.30, 0.40, 0.50)
BREAKOUT_VOLUME_RATIO_GRID = (1.0, 1.5, 2.0)
SWING_HOLD_SESSIONS = (1, 2, 3, 4, 5, 7, 10)
SWING_STOP_PCTS = (0.05, 0.08, 0.10, 0.15, 0.20)

@dataclass(frozen=True)
class DanConfig:
    min_reference_extension_pct: float = 0.15
    min_activity_dollar_turnover: float = 1_000_000.0
    min_retained_gain: float = 0.40
    min_consolidation_minutes: int = 10
    max_pullback_depth: float = 0.50
    min_breakout_volume_ratio: float = 1.0
    volume_lookback_bars: int = 5
    slippage_bps: float = 25.0
    followup_sessions: int = 10


def retained_gain_ratio(impulse_start: Any, impulse_high: Any, reference_price: Any) -> float:
    try:
        start, high, ref = float(impulse_start), float(impulse_high), float(reference_price)
    except (TypeError, ValueError):
        return np.nan
    if not all(isfinite(v) for v in (start, high, ref)) or high <= start:
        return np.nan
    return (ref - start) / (high - start)
```

- [ ] **Step 6: Run focused tests and commit.**

Run: `PYTHONPATH=. pytest tests/test_dan_features.py tests/test_core_models.py -q`

Expected: PASS.

Commit: `feat: add Dan price and retained gain features`

---

### Task 2: Add Dan-only candidate discovery and cache-safe follow-up minute fetching

**Files:**
- Modify: `scanner/multistrategy/study.py`
- Modify: `scanner/multistrategy/config.py` only if a non-Dan shared cache setting is required; do not change existing price defaults.
- Modify: `tests/test_multistrategy_study.py`
- Create: `tests/test_dan_candidate_discovery.py`

**Interfaces:**
- Produces `dan_candidate_context(early, prior_close, cfg=None, optional=None) -> dict[str, Any]`.
- Changes `MultiStrategyStudy.run(include_dan_candidates: bool = False) -> dict[str, Any]` while preserving the current default behaviour.
- Adds `MultiStrategyStudy.ensure_minute_day(symbols: list[str], day: date) -> pd.DataFrame` using a requested-symbol manifest so broader Dan runs cannot silently reuse an incomplete prior cache.
- When enabled, `run()` returns `dan_candidate_contexts` and `daily_bars` in-memory alongside the existing `candidate_contexts`.

- [ ] **Step 1: Write a failing test proving a $125 Dan candidate is included while the existing broad ORB/VWAP flag remains false.**

```python
from scanner.multistrategy.study import broad_candidate_context, dan_candidate_context
from scanner.strategies.dan_irish.config import DanConfig


def test_dan_candidate_can_be_above_existing_30_dollar_cap(early_bars):
    ctx = dan_candidate_context(early_bars, prior_close=100.0, cfg=DanConfig())
    assert ctx["dan_candidate"] is True
    assert ctx["price_bucket"] == "GE_100"
    assert broad_candidate_context(early_bars, prior_close=100.0)["broad_candidate"] is False
```

Use a fixture with a $120+ premarket print and more than $1M turnover.

- [ ] **Step 2: Verify RED.**

Run: `PYTHONPATH=. pytest tests/test_dan_candidate_discovery.py -q`

Expected: FAIL because `dan_candidate_context` does not exist.

- [ ] **Step 3: Implement Dan context separately from `broad_candidate_context`.**

```python
def dan_candidate_context(early, prior_close, cfg=None, optional=None):
    cfg = cfg or DanConfig()
    optional = optional or {}
    base = broad_candidate_context(
        early,
        prior_close,
        cfg=MultiStrategyConfig(min_price=0.01, max_price=1_000_000.0,
                                min_gap_pct=cfg.min_reference_extension_pct,
                                min_activity_dollar_turnover=cfg.min_activity_dollar_turnover),
        optional=optional,
    )
    extension = max(
        base.get("pm_high", np.nan) / prior_close if prior_close else np.nan,
        base.get("hod_1000", np.nan) / prior_close if prior_close else np.nan,
    )
    base["dan_candidate"] = bool(np.isfinite(extension) and extension >= 1.0 + cfg.min_reference_extension_pct)
    base["price_bucket"] = price_bucket(prior_close)
    return base
```

Implementation must not mutate the repository-wide `MultiStrategyConfig` defaults.

- [ ] **Step 4: Add failing regression test for cache widening.**

```python
def test_ensure_minute_day_fetches_symbols_missing_from_existing_manifest(tmp_path, monkeypatch):
    # first cache contains AAA only; second request asks AAA+BBB
    # fake API records only BBB as the second network request
    ...
```

Use an in-test fake API object with `stock_bars()` returning deterministic rows and assert the final cache contains both symbols and the manifest contains `AAA` and `BBB`.

- [ ] **Step 5: Implement manifest-backed cache merge.**

Store manifests at:

`data/cache/multistrategy_alpaca/minute/<date>_<feed>.symbols.json`

Rules:
- no manifest => conservatively treat all requested symbols as missing once, merge/deduplicate, write manifest;
- manifest present => fetch only `requested - manifested`;
- deduplicate on `symbol,timestamp`;
- update manifest only after successful write.

- [ ] **Step 6: Modify `run(include_dan_candidates=False)` so existing callers receive identical `candidate_contexts`; when true, compute a separate Dan frame, fetch minute data for the union of broad + Dan candidates, and return `daily_bars` without serialising it into JSON metadata.**

- [ ] **Step 7: Run regression tests and commit.**

Run: `PYTHONPATH=. pytest tests/test_multistrategy_study.py tests/test_dan_candidate_discovery.py -q`

Expected: PASS, including existing broad-candidate tests.

Commit: `feat: add isolated Dan candidate discovery`

---

### Task 3: Intraday Dan secondary-expansion signal generator

**Files:**
- Create: `scanner/strategies/dan_irish/intraday.py`
- Create: `tests/test_dan_intraday.py`

**Interfaces:**
- Produces `generate_dan_intraday_signals(bars: pd.DataFrame, context: dict[str, Any], cfg: DanConfig | None = None) -> pd.DataFrame`.
- Emits `strategy_id="DAN_IRISH"`, `variant_id="DAN_INTRADAY_SECONDARY"`, `_replay_mode="intraday"`.
- Adds `price_bucket`, `retained_gain_ratio`, `impulse_pct`, `consolidation_minutes`, `pullback_depth`, `breakout_volume_ratio`, `breakout_reference_type`, `attribution="DAN_DERIVED"` to signal rows.

- [ ] **Step 1: Write a failing synthetic test proving confirmation then next-bar entry.**

```python
def test_dan_intraday_waits_for_consolidation_break_and_enters_next_bar():
    out = generate_dan_intraday_signals(
        intraday_secondary_fixture(),
        dan_context(),
        DanConfig(min_reference_extension_pct=0.20,
                  min_consolidation_minutes=3,
                  min_retained_gain=0.60,
                  min_breakout_volume_ratio=1.5),
    )
    row = out.iloc[0]
    assert row["variant_id"] == "DAN_INTRADAY_SECONDARY"
    assert str(row["signal_timestamp"])[11:16] == "09:37"
    assert str(row["entry_timestamp"])[11:16] == "09:38"
    assert row["entry_price_raw"] == intraday_secondary_fixture().iloc[8]["open"]
    assert row["stop_reference"] == row["base_low"]
```

- [ ] **Step 2: Write failing anti-lookahead tests.**

```python
def test_dan_intraday_emits_nothing_before_full_base_duration():
    assert generate_dan_intraday_signals(short_base_fixture(), dan_context(),
                                         DanConfig(min_consolidation_minutes=5)).empty


def test_dan_intraday_rejects_excessive_giveback():
    assert generate_dan_intraday_signals(deep_pullback_fixture(), dan_context(),
                                         DanConfig(min_retained_gain=0.65)).empty
```

- [ ] **Step 3: Verify RED.**

Run: `PYTHONPATH=. pytest tests/test_dan_intraday.py -q`

Expected: FAIL because the generator does not exist.

- [ ] **Step 4: Implement the minimal state sequence.**

Use `attach_session_vwap`, `rolling_prior_volume_median`, `close_location_value` and `SignalRecord` rather than duplicating core feature logic.

Pseudo-implementation must become concrete code with this sequence:

```python
x = attach_session_vwap(bars)
x["prior_volume_median"] = rolling_prior_volume_median(x, cfg.volume_lookback_bars)
x["volume_ratio"] = x["volume"] / x["prior_volume_median"].replace(0, np.nan)
# find first completed impulse >= threshold
# find completed base window after impulse
# calculate base_low/base_high, pullback depth and retained gain from bars available up to confirmation
# require completed close through selected base high
# next row on same session is entry
```

The first implementation uses the consolidation-high breakout; HOD and PM-high breakout families are added as explicit metadata/rule dimensions only after the core signal passes tests.

- [ ] **Step 5: Add tests for price bucket propagation and `attribution="DAN_DERIVED"`.**

- [ ] **Step 6: Run focused tests and commit.**

Run: `PYTHONPATH=. pytest tests/test_dan_intraday.py tests/test_vwap_strategy.py tests/test_orb_strategy.py -q`

Expected: PASS.

Commit: `feat: add Dan intraday secondary expansion signals`

---

### Task 4: Dan swing signal generation for overnight, Day-2 and multi-day compression

**Files:**
- Create: `scanner/strategies/dan_irish/swing.py`
- Create: `tests/test_dan_swing_signals.py`

**Interfaces:**
- Produces `generate_dan_swing_signals(day0_context: dict[str, Any], daily_bars: pd.DataFrame, minute_loader: Callable[[str, date], pd.DataFrame], cfg: DanConfig | None = None) -> pd.DataFrame`.
- Emits variants `DAN_OVERNIGHT_CLOSE_ENTRY`, `DAN_OVERNIGHT_AH_ENTRY`, `DAN_OVERNIGHT_NEXT_OPEN`, `DAN_DAY2_CONTINUATION`, `DAN_MULTIDAY_COMPRESSION`.
- Swing rows use `_replay_mode="swing"` and `attribution="DAN_INSPIRED"` unless later evidence changes it.
- Adds `base_length_sessions`, `day0_retained_gain`, `entry_family`, `day0_hod`, `base_low`, `base_high`.

- [ ] **Step 1: Write failing overnight next-open test proving next-session future bars are not used for qualification.**

```python
def test_overnight_next_open_uses_only_day0_for_signal_and_day1_open_for_entry():
    out = generate_dan_swing_signals(day0_context(), daily_fixture(), minute_loader(), DanConfig())
    row = out[out["variant_id"].eq("DAN_OVERNIGHT_NEXT_OPEN")].iloc[0]
    assert row["signal_timestamp"].date().isoformat() == "2026-08-28"
    assert str(row["entry_timestamp"])[0:10] == "2026-08-31"
    assert row["entry_price_raw"] == day1_minutes().iloc[0]["open"]
```

- [ ] **Step 2: Write failing Day-2 anti-lookahead test.**

```python
def test_day2_breakout_cannot_use_later_day2_high_to_set_breakout_level():
    early_only = day2_minutes().iloc[:20].copy()
    late_spike = day2_minutes().copy()
    late_spike.loc[late_spike.index[-1], "high"] = 99.0
    assert _day2_breakout_level(early_only) == _day2_breakout_level(late_spike.iloc[:20])
```

Keep `_day2_breakout_level` internal if desired; test public output if the project convention avoids private helpers.

- [ ] **Step 3: Write failing compression-base isolation test.**

```python
def test_multiday_base_length_is_encoded_in_rule_identity_metadata():
    out = generate_dan_swing_signals(day0_context(), five_day_daily_fixture(), minute_loader(), DanConfig())
    compression = out[out["variant_id"].eq("DAN_MULTIDAY_COMPRESSION")]
    assert set(compression["base_length_sessions"]) >= {1, 2, 3}
```

- [ ] **Step 4: Verify RED and implement daily qualification + minute confirmation.**

Daily bars determine candidate session structure only from sessions already completed. Minute bars on the breakout session determine signal timestamp and next executable entry.

Concrete rules for V1:
- Day-0 qualification: configured impulse + closing retained gain >= configured threshold.
- Overnight close entry: confirmation after 15:30 ET with close above session VWAP and close-location >= 0.70; entry next minute before 16:00.
- AH entry: completed AH confirmation above regular-session close/HOD reference; entry next available AH minute.
- Next-open entry: Day-0 qualification timestamp remains Day 0; entry is first executable regular-session minute on next session.
- Day-2: base forms from completed Day-2 bars; confirmation closes above completed base high; next bar entry.
- Multi-day compression: completed daily bases of lengths 1-5; breakout session confirmation closes above prior completed base high; next bar entry.

- [ ] **Step 5: Add attribution and variant identity tests.**

- [ ] **Step 6: Run and commit.**

Run: `PYTHONPATH=. pytest tests/test_dan_swing_signals.py -q`

Expected: PASS.

Commit: `feat: add Dan inspired swing signals`

---

### Task 5: Multi-session replay with gap-through stops and censoring

**Files:**
- Create: `scanner/core/multisession_replay.py`
- Create: `tests/test_multisession_replay.py`

**Interfaces:**
- Produces immutable `SwingReplayRule(stop_pct=None, stop_price=None, target_pct=None, target_r_multiple=None, max_hold_sessions=1)`.
- Produces `simulate_multisession_trade(...) -> SwingReplayResult`.
- Produces `replay_swing_signal_grid(...) -> pd.DataFrame`.
- `max_hold_sessions=N` means the terminal exit is the Nth regular-session close strictly after the entry date, unless stop/target exits earlier.

- [ ] **Step 1: Write failing gap-through-stop test.**

```python
def test_long_gap_below_stop_fills_at_first_open_not_stop_price():
    result = simulate_multisession_trade(
        swing_bars_gap_down(), entry_price=10.0, entry_timestamp="2026-08-28 15:59-04:00",
        direction="LONG", rule=SwingReplayRule(stop_price=9.0, max_hold_sessions=1),
        split_end_date="2026-08-31", available_end_date="2026-08-31",
    )
    assert result.exit_reason == "GAP_STOP"
    assert result.exit_price == 8.25
    assert result.return_pct == -0.175
```

- [ ] **Step 2: Write failing same-bar ambiguity test and favourable target-gap test.**

For a bar touching both stop and target after opening inside both levels, assert stop-first. For an opening price above the target, use the configured target price as the conservative target fill.

- [ ] **Step 3: Write failing split-boundary and right-censor tests.**

```python
def test_hold_crossing_split_boundary_is_marked_censored():
    row = replay_swing_signal_grid(..., rules=[SwingReplayRule(stop_pct=.10, target_pct=.20, max_hold_sessions=5)],
                                   split_end_date="2026-09-02", available_end_date="2026-09-15").iloc[0]
    assert row["boundary_censored"] is True
    assert row["selection_eligible_replay"] is False


def test_missing_future_sessions_is_right_censored():
    row = replay_swing_signal_grid(..., rules=[SwingReplayRule(stop_pct=.10, target_pct=.20, max_hold_sessions=10)],
                                   split_end_date="2026-09-30", available_end_date="2026-09-03").iloc[0]
    assert row["right_censored"] is True
    assert row["selection_eligible_replay"] is False
```

- [ ] **Step 4: Verify RED.**

Run: `PYTHONPATH=. pytest tests/test_multisession_replay.py -q`

Expected: FAIL because module is absent.

- [ ] **Step 5: Implement replay.**

Core logic:

```python
if requested_terminal_session > split_end_session:
    boundary_censored = True
if requested_terminal_session > available_end_session:
    right_censored = True
selection_eligible = not boundary_censored and not right_censored
```

For a long stop on each minute bar:

```python
if bar.open <= stop:
    exit_price, reason = float(bar.open), "GAP_STOP"
elif bar.low <= stop:
    exit_price, reason = float(stop), "STOP"
```

Targets remain conservative at the target level. Record `mfe_pct`, `mae_pct`, `trading_days_to_peak`, `calendar_days_to_peak`, `bars_held`, `max_hold_sessions` and censor flags.

- [ ] **Step 6: Run replay tests plus existing intraday replay regression.**

Run: `PYTHONPATH=. pytest tests/test_multisession_replay.py tests/test_core_replay.py -q`

Expected: PASS.

Commit: `feat: add multi session swing replay`

---

### Task 6: Dan swing rule grid and complete-horizon reporting

**Files:**
- Create: `scanner/strategies/dan_irish/rules.py`
- Modify: `scanner/core/reporting.py`
- Create: `tests/test_dan_reporting.py`

**Interfaces:**
- Produces `default_dan_swing_rules(signal: dict) -> list[SwingReplayRule]`.
- Produces `summarize_censoring(replays: pd.DataFrame) -> pd.DataFrame`.
- Produces `summarize_swing_holds(replays: pd.DataFrame) -> pd.DataFrame`.
- Existing `summarize_strategy_replays` remains backward compatible.

- [ ] **Step 1: Write failing rule-grid test.**

```python
def test_dan_swing_rule_grid_contains_all_hold_horizons_and_structural_rules():
    rules = default_dan_swing_rules({"stop_reference": 8.5})
    assert {r.max_hold_sessions for r in rules} == {1, 2, 3, 4, 5, 7, 10}
    assert any(r.stop_price == 8.5 and r.target_r_multiple == 2.0 for r in rules)
    assert any(r.stop_pct == 0.08 for r in rules)
```

- [ ] **Step 2: Write failing reporting test proving censored returns cannot inflate n/PF/expectancy.**

```python
def test_strategy_summary_excludes_noneligible_censored_returns():
    rows = pd.DataFrame([
        replay_row(return_pct=.20, selection_eligible_replay=True),
        replay_row(return_pct=9.00, selection_eligible_replay=False),
    ])
    eligible = rows[rows["selection_eligible_replay"].fillna(True)]
    summary = summarize_strategy_replays(eligible)
    assert summary.iloc[0]["n"] == 1
    assert summary.iloc[0]["expectancy"] == .20
```

- [ ] **Step 3: Implement swing rules.**

Use percentage stops `(0.05, 0.08, 0.10, 0.15, 0.20)`, common percentage targets `(0.05, 0.10, 0.15, 0.20, 0.30, 0.40, 0.50)`, R targets `(1.0, 1.5, 2.0, 3.0, 4.0)` and holds `(1,2,3,4,5,7,10)`.

- [ ] **Step 4: Implement censor and swing-hold summaries without changing current intraday summary semantics.**

Censor summary dimensions: `strategy_id,variant_id,split,max_hold_sessions` with `boundary_censored_n,right_censored_n,eligible_n`.

Swing hold summary dimensions: `strategy_id,variant_id,direction,split,max_hold_sessions,price_bucket,market_cap_bucket` where columns exist.

- [ ] **Step 5: Run tests and commit.**

Run: `PYTHONPATH=. pytest tests/test_dan_reporting.py tests/test_strategy_ranker.py -q`

Expected: PASS; production expectancy hurdle test remains unchanged.

Commit: `feat: add Dan swing rules and reporting`

---

### Task 7: Runner integration, Dan follow-up cache population and common outputs

**Files:**
- Modify: `scripts/run_strategy_research.py`
- Modify: `scanner/multistrategy/study.py`
- Create: `tests/test_dan_runner_integration.py`
- Modify: `tests/test_documented_configs.py` if CLI/documented strategy choices are asserted there.

**Interfaces:**
- `_parse_strategies("all") -> ("orb", "vwap", "serclick", "dan")`.
- `run_research(..., strategies=("dan",))` executes Dan discovery, signals, intraday replay, swing replay and reporting.
- `ResearchResult` adds `price_bucket_summary`, `retained_gain_summary`, `swing_hold_summary`, `overnight_gap_risk`, `censor_summary`.

- [ ] **Step 1: Write failing parser tests.**

```python
def test_parse_strategies_supports_dan_and_all():
    assert runner._parse_strategies("dan") == ("dan",)
    assert "dan" in runner._parse_strategies("all")
```

- [ ] **Step 2: Write failing API-free synthetic runner test.**

Create `_FakeDanStudy.run(include_dan_candidates=True)` returning:
- existing `candidate_contexts` empty;
- one `dan_candidate_contexts` row;
- deterministic `daily_bars` covering Day 0 through Day 3;
- cached minute files for Day 0 through Day 3.

Block HTTP exactly as existing `test_no_cost_end_to_end.py` does.

Assertions:

```python
result = runner.run_research(root=tmp_path, feed="sip", sessions=4,
                             end_date="2026-09-02", strategies=("dan",), min_n=1)
assert "DAN_IRISH" in set(result.signals["strategy_id"])
assert {"intraday", "swing"}.issubset(set(result.signals["_replay_mode"]))
assert (result.output_dir / "price_bucket_summary.csv").exists()
assert (result.output_dir / "swing_hold_summary.csv").exists()
assert (result.output_dir / "overnight_gap_risk.csv").exists()
```

- [ ] **Step 3: Update study invocation.**

When `dan` is selected, call `MultiStrategyStudy.run(include_dan_candidates=True)`. When only ORB/VWAP are selected, preserve current default call and current candidate population.

- [ ] **Step 4: Populate follow-up minute data only for Dan candidate symbols and the next `cfg.followup_sessions` dates known from `daily_bars`.**

Use `study.ensure_minute_day()` so the same cache can be safely widened. Do not fetch the whole equity universe at minute granularity for follow-up sessions.

- [ ] **Step 5: Generate Dan signals.**

For each Dan Day-0 context:
- intraday generator uses Day-0 cache;
- swing generator receives daily bars plus a minute loader backed by the ensured caches.

- [ ] **Step 6: Split replay paths.**

```python
intraday_signals = signals[signals["_replay_mode"].fillna("intraday").eq("intraday")]
swing_signals = signals[signals["_replay_mode"].eq("swing")]
```

Existing `replay_signals()` handles intraday. New `replay_swing_signals()` uses `default_dan_swing_rules` and `replay_swing_signal_grid`.

- [ ] **Step 7: Build ranking source from selection-eligible rows only.**

```python
eligible_replays = replays[
    replays.get("selection_eligible_replay", pd.Series(True, index=replays.index)).fillna(True)
]
summary = summarize_strategy_replays(eligible_replays)
```

Preserve test/forward reporting joins in `rank_strategies`.

- [ ] **Step 8: Write new artifacts.**

Add:
- `price_bucket_summary.csv`
- `retained_gain_summary.csv`
- `swing_hold_summary.csv`
- `overnight_gap_risk.csv`
- `censor_summary.csv`

Keep all current output filenames unchanged.

- [ ] **Step 9: Update `render_news()` to list Dan variants and explicitly label swing variants `Dan-inspired`.**

- [ ] **Step 10: Run integration tests and commit.**

Run: `PYTHONPATH=. pytest tests/test_dan_runner_integration.py tests/test_no_cost_end_to_end.py tests/test_no_cost_vwap_end_to_end.py tests/test_no_cost_serclick_end_to_end.py -q`

Expected: PASS without HTTP requests.

Commit: `feat: integrate Dan strategy family into research runner`

---

### Task 8: Regression protection for SerClick lock, ORB/VWAP isolation and production gate

**Files:**
- Modify: `tests/test_strategy_ranker.py` only to add Dan-specific rows without changing existing expectations.
- Create: `tests/test_dan_regressions.py`

**Interfaces:** No new production interfaces; this task locks invariants.

- [ ] **Step 1: Add test proving Dan selection does not alter ORB/VWAP context defaults.**

```python
def test_existing_multistrategy_price_gate_remains_1_to_30():
    cfg = MultiStrategyConfig()
    assert cfg.min_price == 1.0
    assert cfg.max_price == 30.0
```

- [ ] **Step 2: Add test proving the SerClick constants remain frozen.**

```python
def test_serclick_historical_lock_date_is_unchanged():
    assert runner.SERCLICK_BASELINE_END.isoformat() == "2026-08-27"
```

- [ ] **Step 3: Add ranking test proving a Dan swing row below 10% validation expectancy is visible but not production eligible.**

```python
def test_dan_swing_still_uses_existing_ten_percent_production_hurdle():
    summary = pd.DataFrame([_row("DAN_IRISH", "DAN_DAY2_CONTINUATION", "validation", 1.8, 0.09, n=30)])
    ranked = rank_strategies(summary, min_n=20)
    assert ranked.iloc[0]["production_eligible"] is False
```

Use the local helper shape already established in `tests/test_strategy_ranker.py`.

- [ ] **Step 4: Run targeted and full API-free regressions.**

Run: `PYTHONPATH=. pytest tests/test_dan_regressions.py tests/test_strategy_ranker.py tests/test_multistrategy_study.py -q`

Expected: PASS.

Commit: `test: protect Dan integration invariants`

---

### Task 9: Documentation, CLI smoke and full engineering verification

**Files:**
- Modify: `README.md`
- Modify: `docs/research/multistrategy_methodology.md`
- Modify: `.github/workflows/ci.yml` only if current CI paths do not already execute all `tests/`.

**Interfaces:** User-facing research commands and methodology only.

- [ ] **Step 1: Update README strategy list and commands.**

Document:

```bash
python scripts/run_strategy_research.py --strategy dan --feed sip --sessions 60
python scripts/run_strategy_research.py --strategy all --feed sip --sessions 60
```

State that 60 sessions is an engineering/research smoke horizon for swing logic, not sufficient promotion evidence for 1-10 day holds.

- [ ] **Step 2: Update methodology with exact Dan price buckets, attribution labels, hold semantics, gap-through-stop handling and censor rules.**

Include this explicit sentence:

`A swing replay is excluded from rule-selection metrics whenever its requested future horizon crosses a development/validation/test boundary or extends beyond the available historical data.`

- [ ] **Step 3: Run CLI help smoke.**

Run: `python scripts/run_strategy_research.py --help`

Expected: help text includes `dan` in the strategy description.

- [ ] **Step 4: Run full API-free test suite.**

Run: `PYTHONPATH=. pytest -q`

Expected: zero failures.

- [ ] **Step 5: Run compile verification.**

Run: `python -m compileall -q scanner scripts`

Expected: exit code 0.

- [ ] **Step 6: Confirm no credential material was added.**

Run: `git diff --check && git grep -n -E 'APCA_API_KEY_ID=|APCA_API_SECRET_KEY=|sk-[A-Za-z0-9]' -- . ':!docs/superpowers/plans/2026-08-31-dan-irish-strategy-family.md'`

Expected: `git diff --check` exits cleanly and grep returns no committed credential values.

- [ ] **Step 7: Commit documentation and verification changes.**

Commit: `docs: document Dan intraday and swing research`

---

## Execution Order and Review Gates

1. Tasks 1-2 establish isolated shared features and data access.
2. Task 3 delivers a complete, independently testable Dan intraday strategy.
3. Tasks 4-6 deliver swing signals, replay and reporting without touching runner orchestration until each unit is green.
4. Task 7 integrates the family into the existing CLI and outputs.
5. Task 8 proves existing strategies and promotion gates were not changed.
6. Task 9 performs full verification and documentation.

Each task must follow RED -> verify RED -> GREEN -> verify GREEN -> commit. Do not combine tasks into one unreviewed code dump.

## Completion Evidence Required

Before claiming the implementation complete, capture fresh evidence for:

```bash
PYTHONPATH=. pytest -q
python -m compileall -q scanner scripts
python scripts/run_strategy_research.py --help
```

For a market-data run, use existing Alpaca credentials only through environment secrets. A historical Dan research run is separate from engineering CI and should report the selected feed, date window, signal counts, censor counts, price-bucket counts and all four Dan strategy families without changing the frozen SerClick baseline.
