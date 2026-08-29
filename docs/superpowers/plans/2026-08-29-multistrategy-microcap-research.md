# Multi-Strategy Microcap Research Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the existing Trading Research Lab into a shared, mechanically testable ORB, VWAP Momentum/Reclaim and SerClick/Leo research framework for US $50M-$2B equities without changing the locked SerClick baseline.

**Architecture:** Introduce small shared modules for models, intraday features, chronological validation and direction-aware replay. Strategy packages consume those interfaces and emit one signal schema. The existing `scanner/serclick` package remains operational and becomes a compatibility consumer of shared components only after parity tests prove behaviour is unchanged. A common ranker and runner then compare strategies using identical execution assumptions and development/validation/test/forward rules.

**Tech Stack:** Python 3.12, pandas >=2.1, numpy >=1.26, requests >=2.31, python-dotenv >=1.0, tabulate >=0.9, pytest >=8.0, GitHub Actions, Alpaca SIP/IEX market data through the existing client.

**Spec:** `docs/superpowers/specs/2026-08-29-multistrategy-microcap-research-design.md`

## Global Constraints

- Research and paper/backtest validation only; do not add live order routing.
- Preserve the existing Leo gates exactly: PM high / prior close > 1.20 with PM dollar turnover > $10M; HOD through 09:59 / prior close > 1.20 with 09:30-09:59 dollar turnover > $5M.
- Preserve next-executable-one-minute-bar entry and the existing 25 bps SerClick baseline assumption.
- Add slippage research scenarios of 10, 25, 50, 75 and 100 bps; never assume a signal-bar close fill.
- Primary known-cap universe is $50M-$2B; market caps below $50M and above/equal $2B are excluded from the primary strategy leaderboard. Unknown historical market cap remains `UNKNOWN` and is never backfilled with future information.
- Initial price research range is $1-$30.
- Development, validation, locked test and prospective-forward periods remain chronological. Prospective-forward observations may be reported but may never select or tune parameters.
- Long and short variants remain separate. Historical short-locate availability is not assumed; short results are labelled signal expectancy unless locate data is available.
- Missing float, catalyst, quote-spread or halt data stays explicitly unknown; no silent imputation.
- Same-minute stop-and-target ambiguity is resolved conservatively against the position.
- Ordinary volatility or suspicious prints are labelled market-quality risk, not asserted to be manipulation.
- Keep the current dependency set unless a later task demonstrates a dependency is essential; no paid service or new charge is introduced by this implementation.

---

### Task 1: Add shared models and chronological validation

**Files:**
- Create: `scanner/core/__init__.py`
- Create: `scanner/core/models.py`
- Create: `scanner/core/validation.py`
- Create: `tests/test_core_models.py`
- Create: `tests/test_validation.py`

**Interfaces:**
- Produces: `SignalRecord.to_dict() -> dict`, `market_cap_in_primary_universe(value) -> bool`, `chronological_split(sessions, development_sessions, validation_sessions, test_sessions) -> dict[date, str]`, `selectable_splits() -> tuple[str, ...]`.
- Consumers: ORB, VWAP, SerClick adapter, replay, ranking and runner tasks.

- [ ] **Step 1: Write failing signal-schema and universe-boundary tests**

```python
from scanner.core.models import SignalRecord, market_cap_in_primary_universe


def test_primary_universe_is_50m_through_under_2b():
    assert market_cap_in_primary_universe(50_000_000) is True
    assert market_cap_in_primary_universe(299_999_999) is True
    assert market_cap_in_primary_universe(300_000_000) is True
    assert market_cap_in_primary_universe(1_999_999_999) is True
    assert market_cap_in_primary_universe(49_999_999) is False
    assert market_cap_in_primary_universe(2_000_000_000) is False
    assert market_cap_in_primary_universe(float("nan")) is False


def test_signal_record_emits_common_strategy_fields():
    signal = SignalRecord(
        strategy_id="ORB",
        variant_id="ORB_LONG_BREAK",
        symbol="AAA",
        date="2026-08-28",
        direction="LONG",
        signal_timestamp="2026-08-28 09:36:00-04:00",
        reference_price=5.00,
        entry_timestamp="2026-08-28 09:37:00-04:00",
        entry_price_raw=5.05,
        entry_price_slipped=5.062625,
        stop_reference=4.80,
    )
    out = signal.to_dict()
    assert out["strategy_id"] == "ORB"
    assert out["direction"] == "LONG"
    assert "market_cap_bucket" in out
    assert "float_bucket" in out
    assert "gap_bucket" in out
    assert "rvol_bucket" in out
    assert "time_of_day_bucket" in out
    assert "catalyst_class" in out
```

- [ ] **Step 2: Run the tests and confirm import failures**

Run: `PYTHONPATH=. pytest tests/test_core_models.py -q`

Expected: FAIL because `scanner.core.models` does not exist.

- [ ] **Step 3: Implement immutable shared signal models and explicit unknown defaults**

```python
@dataclass(frozen=True)
class SignalRecord:
    strategy_id: str
    variant_id: str
    symbol: str
    date: str
    direction: str
    signal_timestamp: object
    reference_price: float
    entry_timestamp: object
    entry_price_raw: float
    entry_price_slipped: float
    stop_reference: float | None = None
    market_cap: float | None = None
    market_cap_bucket: str = "UNKNOWN"
    float_shares: float | None = None
    float_bucket: str = "UNKNOWN"
    gap_bucket: str = "UNKNOWN"
    rvol_bucket: str = "UNKNOWN"
    time_of_day_bucket: str = "UNKNOWN"
    catalyst_class: str = "UNKNOWN"

    def to_dict(self) -> dict:
        return asdict(self)
```

Implement `market_cap_in_primary_universe()` using `50_000_000 <= cap < 2_000_000_000` and finite-number checks.

- [ ] **Step 4: Write failing chronological-split tests**

```python
from datetime import date, timedelta
from scanner.core.validation import chronological_split, selectable_splits


def test_chronological_split_never_moves_forward_into_selection():
    sessions = [date(2026, 1, 1) + timedelta(days=i) for i in range(8)]
    out = chronological_split(sessions, development_sessions=3, validation_sessions=2, test_sessions=2)
    assert [out[d] for d in sessions] == [
        "development", "development", "development",
        "validation", "validation",
        "test", "test", "forward",
    ]
    assert selectable_splits() == ("development", "validation")
```

- [ ] **Step 5: Implement validation helpers and run both test files**

Run: `PYTHONPATH=. pytest tests/test_core_models.py tests/test_validation.py -q`

Expected: PASS.

- [ ] **Step 6: Commit Task 1**

```bash
git add scanner/core tests/test_core_models.py tests/test_validation.py
git commit -m "feat: add shared research models and validation"
```

---

### Task 2: Add no-lookahead intraday feature primitives

**Files:**
- Create: `scanner/core/features.py`
- Create: `tests/test_core_features.py`

**Interfaces:**
- Consumes: one-minute OHLCV bars containing `timestamp` or `timestamp_et`.
- Produces: `prepare_intraday_bars(df) -> DataFrame`, `opening_range(df, minutes=5) -> dict`, `close_location_value(row) -> float`, `rolling_prior_volume_median(df, lookback_bars=5) -> Series`, `attach_session_vwap(df) -> DataFrame`, `bucket_gap`, `bucket_rvol`, `bucket_time_of_day`.

- [ ] **Step 1: Write failing no-lookahead feature tests**

```python
import pandas as pd
from scanner.core.features import attach_session_vwap, opening_range, rolling_prior_volume_median


def test_opening_range_uses_only_0930_through_0934_bars():
    bars = make_minute_bars([
        ("2026-08-28 09:30", 5.0, 5.2, 4.9, 5.1, 100),
        ("2026-08-28 09:34", 5.1, 5.4, 5.0, 5.3, 200),
        ("2026-08-28 09:35", 5.3, 6.5, 5.2, 6.4, 9999),
    ])
    result = opening_range(bars, minutes=5)
    assert result["high"] == 5.4
    assert result["low"] == 4.9


def test_prior_volume_median_excludes_current_bar():
    bars = pd.DataFrame({"volume": [10, 20, 30, 40, 50, 1000]})
    out = rolling_prior_volume_median(bars, lookback_bars=5)
    assert out.iloc[-1] == 30
```

- [ ] **Step 2: Run and confirm failures**

Run: `PYTHONPATH=. pytest tests/test_core_features.py -q`

Expected: FAIL because the feature module is absent.

- [ ] **Step 3: Implement ET timestamps, cumulative session VWAP and bucket helpers**

The VWAP helper must compute cumulative `(price * volume) / cumulative volume` using the provider VWAP where valid, otherwise typical price `(high + low + close) / 3`, and must reset by symbol/session date. Rolling features use `.shift(1)` before the rolling window.

- [ ] **Step 4: Add CLV and time-bucket edge-case tests and run the file**

```python
def test_close_location_value_is_one_at_high_and_zero_at_low():
    assert close_location_value({"high": 5.0, "low": 4.0, "close": 5.0}) == 1.0
    assert close_location_value({"high": 5.0, "low": 4.0, "close": 4.0}) == 0.0
```

Run: `PYTHONPATH=. pytest tests/test_core_features.py -q`

Expected: PASS.

- [ ] **Step 5: Commit Task 2**

```bash
git add scanner/core/features.py tests/test_core_features.py
git commit -m "feat: add no-lookahead intraday features"
```

---

### Task 3: Generalise replay to long and short trades with execution diagnostics

**Files:**
- Create: `scanner/core/replay.py`
- Create: `tests/test_core_replay.py`
- Modify: `scanner/serclick/replay.py`
- Modify: `tests/test_replay.py`

**Interfaces:**
- Consumes: common signal dict/Series and OHLCV bars.
- Produces: `ReplayRule`, `ReplayResult`, `apply_entry_slippage(price, direction, bps)`, `simulate_trade(bars, entry_price, entry_timestamp, direction, rule)`, `replay_signal_grid(...)`.
- Compatibility: `scanner.serclick.replay.ReplayRule`, `simulate_long_trade`, `default_rule_grid` and `replay_signal_grid` remain import-compatible.

- [ ] **Step 1: Write failing long/short conservative-ordering tests**

```python
from scanner.core.replay import ReplayRule, simulate_trade


def test_short_same_bar_stop_and_target_assumes_stop_first():
    bars = bars_at([("2026-08-28 10:00", 10.0, 10.6, 8.8, 9.2)])
    result = simulate_trade(
        bars, 10.0, "2026-08-28 10:00:00-04:00", "SHORT",
        ReplayRule(stop_pct=0.05, target_pct=0.10, max_hold_minutes=30),
    )
    assert result.exit_reason == "STOP_SAME_BAR"
    assert result.return_pct == -0.05


def test_long_and_short_slippage_move_entry_against_trader():
    assert apply_entry_slippage(10.0, "LONG", 25) == 10.025
    assert apply_entry_slippage(10.0, "SHORT", 25) == 9.975
```

- [ ] **Step 2: Run the core replay tests and confirm failures**

Run: `PYTHONPATH=. pytest tests/test_core_replay.py -q`

Expected: FAIL because `scanner.core.replay` is absent.

- [ ] **Step 3: Implement direction-aware replay**

`ReplayResult` must include at least `exit_reason`, `exit_timestamp`, `exit_price`, `return_pct`, `bars_held`, `mfe_pct`, `mae_pct` and `r_multiple`. Long returns use `exit / entry - 1`; short returns use `entry / exit - 1` only for diagnostic raw return if percentage symmetry is documented consistently, while stop/target outcomes remain exactly `-stop_pct` / `+target_pct`. Use one convention consistently in tests and reporting.

- [ ] **Step 4: Add MFE/MAE tests**

```python
def test_long_replay_records_mfe_and_mae_before_time_exit():
    result = simulate_trade(
        bars_at([
            ("2026-08-28 10:00", 10.0, 10.5, 9.8, 10.1),
            ("2026-08-28 10:01", 10.1, 10.8, 9.9, 10.2),
        ]),
        10.0, "2026-08-28 10:00:00-04:00", "LONG",
        ReplayRule(0.20, 0.20, 2),
    )
    assert round(result.mfe_pct, 4) == 0.08
    assert round(result.mae_pct, 4) == -0.02
```

- [ ] **Step 5: Replace SerClick replay internals with a compatibility wrapper only after parity tests are added**

Keep the existing long-only public function:

```python
def simulate_long_trade(bars, entry_price, entry_timestamp, rule):
    return simulate_trade(bars, entry_price, entry_timestamp, "LONG", rule)
```

Preserve the current SerClick default 135-rule grid exactly.

- [ ] **Step 6: Run legacy and shared replay tests**

Run: `PYTHONPATH=. pytest tests/test_core_replay.py tests/test_replay.py -q`

Expected: PASS, including the legacy same-bar stop-first and 135-rule assertions.

- [ ] **Step 7: Commit Task 3**

```bash
git add scanner/core/replay.py scanner/serclick/replay.py tests/test_core_replay.py tests/test_replay.py
git commit -m "feat: add shared direction-aware trade replay"
```

---

### Task 4: Implement Stocks-in-Play 5-minute ORB signal generation

**Files:**
- Create: `scanner/strategies/__init__.py`
- Create: `scanner/strategies/orb_stocks_in_play/__init__.py`
- Create: `scanner/strategies/orb_stocks_in_play/config.py`
- Create: `scanner/strategies/orb_stocks_in_play/strategy.py`
- Create: `tests/test_orb_strategy.py`

**Interfaces:**
- Consumes: one symbol-day of one-minute bars plus context dict with `prior_close`, market cap, PM dollar turnover, gap/RVOL inputs and optional float/catalyst data.
- Produces: `generate_orb_signals(bars, context, cfg=None) -> DataFrame` in the common signal schema.

- [ ] **Step 1: Write failing 09:35 timing and next-bar-entry tests**

```python
def test_orb_long_requires_close_above_locked_five_minute_range_and_enters_next_bar():
    bars = orb_fixture_with_breakout_at_0936_and_next_bar_at_0937()
    out = generate_orb_signals(
        bars,
        context={
            "symbol": "AAA", "date": "2026-08-28", "prior_close": 4.0,
            "market_cap": 150_000_000, "pm_gap_pct": 0.25,
            "pm_dollar_turnover": 5_000_000, "opening_rvol": 6.0,
        },
        cfg=ORBConfig(min_gap_pct=0.10, min_pm_dollar_turnover=2_000_000,
                      min_opening_rvol=3.0, min_breakout_volume_ratio=1.5),
    )
    row = out[out["direction"].eq("LONG")].iloc[0]
    assert str(row["signal_timestamp"])[11:16] == "09:36"
    assert str(row["entry_timestamp"])[11:16] == "09:37"
    assert row["strategy_id"] == "ORB"
```

- [ ] **Step 2: Run and confirm ORB test failure**

Run: `PYTHONPATH=. pytest tests/test_orb_strategy.py -q`

Expected: FAIL because the ORB package is absent.

- [ ] **Step 3: Implement candidate gates and long breakout variant**

`ORBConfig` contains explicit values for the active variant and separate research-grid constants for gap thresholds `(0.05, 0.08, 0.10, 0.15, 0.20)`, PM turnover `(1e6, 2e6, 5e6, 10e6)`, opening RVOL `(3, 5, 10)`, breakout volume ratio `(1.5, 2, 3)` and CLV thresholds `(0.60, 0.75)`. No grid value is labelled optimal.

- [ ] **Step 4: Add negative tests for wick-only breaks, below-VWAP breaks and low-volume breaks**

```python
def test_orb_wick_without_close_above_range_is_not_signal():
    out = generate_orb_signals(orb_fixture_wick_only(), valid_orb_context())
    assert out.empty
```

- [ ] **Step 5: Implement pullback long, negative-gap short and failed-gap reversal as distinct `variant_id` values**

Short variants must set `direction="SHORT"` and `borrow_status="UNKNOWN"` in setup metadata rather than asserting borrow availability.

- [ ] **Step 6: Run ORB tests**

Run: `PYTHONPATH=. pytest tests/test_orb_strategy.py -q`

Expected: PASS.

- [ ] **Step 7: Commit Task 4**

```bash
git add scanner/strategies tests/test_orb_strategy.py
git commit -m "feat: add stocks-in-play ORB strategy"
```

---

### Task 5: Implement High-RVOL VWAP Momentum/Reclaim signal generation

**Files:**
- Create: `scanner/strategies/vwap_momentum/__init__.py`
- Create: `scanner/strategies/vwap_momentum/config.py`
- Create: `scanner/strategies/vwap_momentum/strategy.py`
- Create: `tests/test_vwap_strategy.py`

**Interfaces:**
- Consumes: symbol-day one-minute bars plus prior-close/cap/gap/RVOL/turnover context.
- Produces: `generate_vwap_signals(bars, context, cfg=None) -> DataFrame` using common signal fields.

- [ ] **Step 1: Write failing impulse-pullback-reclaim test**

```python
def test_vwap_long_requires_prior_impulse_touch_and_reclaim_then_next_bar_entry():
    out = generate_vwap_signals(
        vwap_reclaim_fixture(),
        context={
            "symbol": "AAA", "date": "2026-08-28", "prior_close": 4.0,
            "market_cap": 200_000_000, "pm_gap_pct": 0.15,
            "pm_dollar_turnover": 5_000_000, "opening_rvol": 6.0,
        },
        cfg=VWAPConfig(min_gap_pct=0.10, min_impulse_pct=0.15,
                       min_rvol=3.0, min_retained_gain=0.60,
                       min_reclaim_volume_ratio=1.5),
    )
    row = out[out["variant_id"].eq("VWAP_LONG_RECLAIM")].iloc[0]
    assert row["direction"] == "LONG"
    assert row["entry_timestamp"] > row["signal_timestamp"]
```

- [ ] **Step 2: Run and confirm failure**

Run: `PYTHONPATH=. pytest tests/test_vwap_strategy.py -q`

Expected: FAIL because the VWAP strategy package is absent.

- [ ] **Step 3: Implement impulse, retained-gain, VWAP-touch and reclaim state logic**

Research grids remain explicit: gap `(0.05, 0.10, 0.15, 0.20)`, impulse `(0.10, 0.15, 0.20, 0.30)`, PM/open turnover `(2e6, 5e6, 10e6)`, RVOL `(3, 5, 10)`, retained gain `(0.40, 0.60, 0.70, 0.80)`, reclaim volume ratio `(1.5, 2, 3)`.

- [ ] **Step 4: Add failure tests for no VWAP touch, insufficient retained gain and reclaim without volume confirmation**

Run: `PYTHONPATH=. pytest tests/test_vwap_strategy.py -q`

Expected: failing tests until all gates are implemented.

- [ ] **Step 5: Implement VWAP rejection short as separate variant**

Use `variant_id="VWAP_SHORT_REJECTION"`, `direction="SHORT"`, and preserve unknown borrow availability.

- [ ] **Step 6: Run VWAP tests**

Run: `PYTHONPATH=. pytest tests/test_vwap_strategy.py -q`

Expected: PASS.

- [ ] **Step 7: Commit Task 5**

```bash
git add scanner/strategies/vwap_momentum tests/test_vwap_strategy.py
git commit -m "feat: add high-rvol VWAP momentum strategy"
```

---

### Task 6: Add a SerClick/Leo shared-strategy adapter with parity tests

**Files:**
- Create: `scanner/strategies/serclick_leo/__init__.py`
- Create: `scanner/strategies/serclick_leo/config.py`
- Create: `scanner/strategies/serclick_leo/strategy.py`
- Create: `tests/test_serclick_adapter.py`

**Interfaces:**
- Consumes: existing `SerClickConfig`, `classify_early_day`, `analyze_candidate_day` outputs.
- Produces: `adapt_serclick_ignitions(ignitions) -> DataFrame` with `strategy_id="SERCLICK_LEO"` and common signal fields.

- [ ] **Step 1: Write failing parity tests for locked Leo gates**

```python
def test_adapter_does_not_change_locked_leo_thresholds():
    cfg = SerClickStrategyConfig()
    assert cfg.extension_ratio == 1.20
    assert cfg.pm_dollar_turnover_min == 10_000_000.0
    assert cfg.open30_dollar_turnover_min == 5_000_000.0
```

- [ ] **Step 2: Write signal-mapping test**

```python
def test_serclick_ignition_maps_to_common_schema_without_repricing_entry():
    source = pd.DataFrame([{
        "symbol": "AAA", "date": "2026-08-28", "split": "forward",
        "population": "BOTH", "ignition_window": "10:30-15:00",
        "timestamp": "2026-08-28 11:00:00-04:00",
        "entry_timestamp": "2026-08-28 11:01:00-04:00",
        "entry_price_raw": 4.00, "entry_price_slipped": 4.01,
    }])
    out = adapt_serclick_ignitions(source)
    assert out.iloc[0]["entry_price_slipped"] == 4.01
    assert out.iloc[0]["variant_id"] == "LEO_BOTH_MIDDAY"
```

- [ ] **Step 3: Implement a thin adapter; do not reimplement the state machine**

The adapter maps existing SerClick events to the common schema. Morning signals map to `MORNING_OBSERVATION`; LEO BOTH 10:30-15:00 to `LEO_BOTH_MIDDAY`; LEO BOTH 16:00-20:00 to `LEO_BOTH_AH`. Existing source fields remain available as metadata columns.

- [ ] **Step 4: Run legacy feature/reporting tests plus adapter tests**

Run: `PYTHONPATH=. pytest tests/test_features.py tests/test_reporting.py tests/test_serclick_adapter.py -q`

Expected: PASS.

- [ ] **Step 5: Commit Task 6**

```bash
git add scanner/strategies/serclick_leo tests/test_serclick_adapter.py
git commit -m "feat: adapt SerClick signals to shared schema"
```

---

### Task 7: Add common reporting, slippage resilience and strategy ranking

**Files:**
- Create: `scanner/portfolio/__init__.py`
- Create: `scanner/portfolio/strategy_ranker.py`
- Create: `scanner/core/reporting.py`
- Create: `tests/test_strategy_ranker.py`
- Create: `tests/test_core_reporting.py`

**Interfaces:**
- Produces: `profit_factor(returns)`, `summarize_strategy_replays(replays)`, `slippage_resilience(summary)`, `rank_strategies(summary, min_n=20) -> DataFrame`.
- Selection inputs: development and validation only. Test and forward columns may be joined for reporting after a rule identity is fixed, never for choosing the rule.

- [ ] **Step 1: Write failing forward-leakage test**

```python
def test_ranker_ignores_forward_when_selecting_rule():
    rows = replay_rows_with_mediocre_validation_and_amazing_forward_for_bad_rule()
    ranked = rank_strategies(rows, min_n=2)
    assert ranked.iloc[0]["rule_id"] == "VALIDATION_WINNER"
```

- [ ] **Step 2: Write slippage break-even tests**

```python
def test_slippage_resilience_reports_first_pf_below_thresholds():
    table = pd.DataFrame([
        {"slippage_bps": 10, "profit_factor": 1.8},
        {"slippage_bps": 25, "profit_factor": 1.4},
        {"slippage_bps": 50, "profit_factor": 1.1},
        {"slippage_bps": 75, "profit_factor": 0.9},
    ])
    out = slippage_resilience(table)
    assert out["pf_below_1_2_bps"] == 50
    assert out["pf_below_1_0_bps"] == 75
```

- [ ] **Step 3: Implement reporting metrics**

Include n, trades/day when dates exist, expectancy, median return, win rate, PF, mean/median R, MFE, MAE, max drawdown from sequential trade returns, £1,000 position examples, stop size, strategy/variant/direction, market-cap bucket and slippage scenario.

- [ ] **Step 4: Implement robustness ranking**

Use explicit normalized components for validation PF, validation expectancy, log sample size, median return, drawdown penalty and slippage resilience. Nearby-parameter/subgroup stability fields contribute only when present. Keep raw component columns in output so ranking is auditable.

- [ ] **Step 5: Add n=20/50/100 eligibility flags and segmentation tests**

Run: `PYTHONPATH=. pytest tests/test_core_reporting.py tests/test_strategy_ranker.py -q`

Expected: PASS.

- [ ] **Step 6: Commit Task 7**

```bash
git add scanner/core/reporting.py scanner/portfolio tests/test_core_reporting.py tests/test_strategy_ranker.py
git commit -m "feat: add cross-strategy research ranking"
```

---

### Task 8: Add a multi-strategy cached-data research runner

**Files:**
- Create: `scripts/run_strategy_research.py`
- Create: `tests/test_strategy_runner.py`
- Modify: `scanner/serclick/pipeline.py`

**Interfaces:**
- CLI: `python scripts/run_strategy_research.py --strategy all --feed sip --sessions 60 --end-date YYYY-MM-DD --root .`
- Output: `data/research/multistrategy/<run_id>/signals.csv`, `replay_grid.csv`, `strategy_summary.csv`, `leaderboard.csv`, `slippage_summary.csv`, `run_meta.json`; mirrors compact outputs into `data/latest/`.

- [ ] **Step 1: Write failing runner test using a temporary cache**

```python
def test_runner_combines_common_schema_without_live_api(tmp_path):
    seed_cached_symbol_day(tmp_path)
    result = run_cached_research(root=tmp_path, feed="sip", strategies=("orb", "vwap"))
    assert set(result.signals["strategy_id"]) <= {"ORB", "VWAP"}
    assert result.output_dir.exists()
```

- [ ] **Step 2: Implement generic cached minute-data iterator**

Extract only cache reading mechanics from `scanner.serclick.pipeline` into a reusable helper without changing SerClick cache layout. Preserve `run_replay_from_cache()` behaviour for existing callers.

- [ ] **Step 3: Implement the runner with strategy registry**

Use registry keys `orb`, `vwap`, `serclick`, `all`. Each generator receives bars plus explicit context. When required candidate context is unavailable, record a skipped/unknown reason rather than fabricate RVOL/float/news values.

- [ ] **Step 4: Generate all five slippage scenarios through the shared replay engine**

Each replay row includes `slippage_bps` and the entry price produced by that scenario. Existing SerClick 25-bps results remain directly comparable.

- [ ] **Step 5: Run runner and existing pipeline tests**

Run: `PYTHONPATH=. pytest tests/test_strategy_runner.py tests/test_pipeline.py -q`

Expected: PASS.

- [ ] **Step 6: Commit Task 8**

```bash
git add scripts/run_strategy_research.py scanner/serclick/pipeline.py tests/test_strategy_runner.py tests/test_pipeline.py
git commit -m "feat: add multi-strategy cached research runner"
```

---

### Task 9: Add research artifacts, README guidance and CI coverage

**Files:**
- Modify: `README.md`
- Modify: `.github/workflows/ci.yml`
- Create: `docs/research/multistrategy_methodology.md`
- Create: `tests/test_documented_configs.py`

**Interfaces:**
- CI remains API-free: install, unit tests, compile only.
- Research runner remains manually invokable. No new paid service and no automatically scheduled multi-strategy remote run is enabled in this task.

- [ ] **Step 1: Add config-documentation parity test**

```python
def test_documented_slippage_grid_matches_shared_config():
    assert DEFAULT_SLIPPAGE_BPS == (10, 25, 50, 75, 100)
```

- [ ] **Step 2: Update CI push branches to include the implementation branch**

Add `multistrategy-microcap-research-v1` alongside the existing SerClick branch while keeping pull requests to `main`.

- [ ] **Step 3: Document the three strategies and evidence labels**

README/methodology must distinguish `HYPOTHESIS`, `VALIDATED`, `LOCKED_TEST`, and `FORWARD` outputs and state that high PF with small n is not sufficient for promotion.

- [ ] **Step 4: Document local commands without triggering market-data charges**

```bash
pip install -r requirements.txt
PYTHONPATH=. pytest -q
python -m compileall -q scanner scripts
python scripts/run_strategy_research.py --strategy all --feed sip --sessions 60
```

The final command is documented for users with existing data/API access; it is not automatically executed by CI.

- [ ] **Step 5: Run full unit suite and compile**

Run: `PYTHONPATH=. pytest -q`

Run: `python -m compileall -q scanner scripts`

Expected: both commands exit 0.

- [ ] **Step 6: Commit Task 9**

```bash
git add README.md .github/workflows/ci.yml docs/research/multistrategy_methodology.md tests/test_documented_configs.py
git commit -m "docs: document multi-strategy research workflow"
```

---

### Task 10: Repository-level verification and pull request

**Files:** all files changed by Tasks 1-9.

**Interfaces:** pull request from `multistrategy-microcap-research-v1` to `main`.

- [ ] **Step 1: Run complete local verification once more**

Run: `PYTHONPATH=. pytest -q`

Run: `python -m compileall -q scanner scripts`

Expected: zero failures and zero compile errors.

- [ ] **Step 2: Verify legacy SerClick invariants from tests**

Confirm tests still enforce the 1.20 extension, $10M PM turnover, $5M open-30 turnover, next-bar entry compatibility, conservative same-bar replay and 135-rule legacy grid.

- [ ] **Step 3: Inspect branch diff against main**

Confirm there are no `.env`, keys, cached data, generated research artifacts, database files or live-order code in the diff.

- [ ] **Step 4: Open the pull request**

Title: `Add multi-strategy microcap research framework`

Body must summarize shared core, ORB, VWAP, SerClick compatibility, ranking and tests; explicitly state that no new paid remote research run has been triggered.

- [ ] **Step 5: Inspect GitHub CI for the pull request**

If CI fails, use the failing job logs, reproduce the failure with the smallest relevant test, fix through TDD and push a new commit.

- [ ] **Step 6: Merge only after CI is green**

The user's standing approval covers the merge when it has no new cost. Do not trigger a chargeable API/data/action run as part of merge verification.
