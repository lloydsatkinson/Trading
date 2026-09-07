# Merciless-Q Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a mechanically defined Merciless-Q strategy family with repeated-entry and friction-resilience analytics to the existing multi-strategy microcap research platform.

**Architecture:** Implement Merciless-Q as a new strategy module that consumes the same `bars + context` interface as ORB and VWAP, emits standard `SignalRecord` rows plus Merciless metadata, and reuses the shared replay/ranking pipeline. Extend the unified runner only at the strategy-registration and reporting edges, and add standalone Merciless summary functions so the existing shared engine stays stable.

**Tech Stack:** Python 3, pandas, numpy, pytest, existing Alpaca cache/replay/reporting modules.

**Spec:** `docs/superpowers/specs/2026-09-02-merciless-q-design.md`

## Global Constraints

- No live order routing.
- Signal candle must complete before entry; entry is the next executable one-minute bar.
- No future HOD/session-close/future market-cap information in features.
- Do not invent historical bid/ask spread, borrow or SSR data.
- Preserve existing 10/25/50/75/100-bps shared execution stress and stop-first ambiguity.
- Locked test and forward splits must never tune Merciless thresholds or score weights.
- V1 implements four variants only: `MMQ_FIRST_PULLBACK`, `MMQ_MICRO_BREAKOUT`, `MMQ_VWAP_RESET`, `MMQ_TRAP_RECLAIM`.

---

### Task 1: Merciless feature/config module and first-pullback generator

**Files:**
- Create: `scanner/strategies/merciless_q/__init__.py`
- Create: `scanner/strategies/merciless_q/config.py`
- Create: `scanner/strategies/merciless_q/strategy.py`
- Create: `tests/test_merciless_q_strategy.py`

**Interfaces:**
- Consumes: `scanner.core.features.attach_session_vwap`, `close_location_value`, `rolling_prior_volume_median`; `scanner.core.models.SignalRecord`; `scanner.core.replay.apply_entry_slippage`.
- Produces: `MercilessConfig`; `generate_merciless_signals(bars: pd.DataFrame, context: dict[str, Any], cfg: MercilessConfig | None = None) -> pd.DataFrame`.

- [ ] **Step 1: Write failing config/candidate/first-pullback tests**

```python
from scanner.strategies.merciless_q.config import MercilessConfig
from scanner.strategies.merciless_q.strategy import generate_merciless_signals


def test_merciless_requires_impulse(valid_runner_bars, runner_context):
    cfg = MercilessConfig(min_impulse_pct=0.20)
    out = generate_merciless_signals(valid_runner_bars, runner_context, cfg)
    assert out.empty


def test_first_pullback_uses_next_bar_entry(first_pullback_bars, runner_context):
    out = generate_merciless_signals(first_pullback_bars, runner_context)
    row = out[out["variant_id"].eq("MMQ_FIRST_PULLBACK")].iloc[0]
    assert str(row["entry_timestamp"]) == str(first_pullback_bars.iloc[-1]["timestamp_et"])
    assert row["sequence_number"] == 1
    assert 0 <= row["mmq_score"] <= 100
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=. pytest -q tests/test_merciless_q_strategy.py`

Expected: FAIL because `scanner.strategies.merciless_q` does not exist.

- [ ] **Step 3: Implement broad Merciless config and common feature preparation**

Create `MercilessConfig` with the exact defaults in the spec. In `strategy.py`, add helpers for finite-number coercion, bar range, upper/lower wick ratio, efficiency, candidate qualification, and a common signal-construction function that creates `SignalRecord(strategy_id="MERCILESS_Q", ...)` and appends `mmq_score`, `sequence_number`, `minutes_since_prior_signal`, and `runner_age_minutes`.

- [ ] **Step 4: Implement `MMQ_FIRST_PULLBACK` minimally**

Required logic:

```python
# completed-bar only
running_high = high.cummax()
impulse_pct = running_high / prior_close - 1.0
first_impulse_idx = first index where impulse_pct >= cfg.min_impulse_pct

# later contraction window
peak = max(high since first_impulse_idx)
pullback_fraction = (peak - low) / max(peak - prior_close, eps)
retained_gain = (low - prior_close) / max(peak - prior_close, eps)

# trigger bar must close above prior micro-pivot with CLV and volume confirmation
trigger = (
    close > prior_contraction_high
    and clv >= cfg.min_clv
    and volume_ratio >= cfg.min_breakout_volume_ratio
    and upper_wick_ratio <= cfg.max_upper_wick_ratio
)
# entry is next bar open
```

Emit at most one first-pullback signal before Task 3 introduces generalized repeats.

- [ ] **Step 5: Run focused tests**

Run: `PYTHONPATH=. pytest -q tests/test_merciless_q_strategy.py`

Expected: PASS.

- [ ] **Step 6: Commit**

Commit message: `feat: add Merciless-Q first pullback signal`

---

### Task 2: Add micro-breakout, VWAP reset and trap-reclaim variants

**Files:**
- Modify: `scanner/strategies/merciless_q/strategy.py`
- Modify: `tests/test_merciless_q_strategy.py`

**Interfaces:**
- Consumes: Task 1 feature frame and signal-construction helper.
- Produces: four variant IDs from a single `generate_merciless_signals` call.

- [ ] **Step 1: Add failing synthetic tests for each new variant**

```python
def test_micro_breakout_requires_repeated_tests_and_rejects_wicky_breakout(flat_top_bars, wicky_flat_top_bars, runner_context):
    good = generate_merciless_signals(flat_top_bars, runner_context)
    bad = generate_merciless_signals(wicky_flat_top_bars, runner_context)
    assert "MMQ_MICRO_BREAKOUT" in set(good["variant_id"])
    assert "MMQ_MICRO_BREAKOUT" not in set(bad["variant_id"])


def test_vwap_reset_reclaims_after_touch_only(vwap_reset_bars, runner_context):
    out = generate_merciless_signals(vwap_reset_bars, runner_context)
    assert "MMQ_VWAP_RESET" in set(out["variant_id"])


def test_trap_reclaim_requires_failed_downside_break(trap_bars, no_trap_bars, runner_context):
    assert "MMQ_TRAP_RECLAIM" in set(generate_merciless_signals(trap_bars, runner_context)["variant_id"])
    assert "MMQ_TRAP_RECLAIM" not in set(generate_merciless_signals(no_trap_bars, runner_context)["variant_id"])
```

- [ ] **Step 2: Run focused tests and confirm failure**

Run: `PYTHONPATH=. pytest -q tests/test_merciless_q_strategy.py`

Expected: new-variant assertions FAIL.

- [ ] **Step 3: Implement `MMQ_MICRO_BREAKOUT`**

Use completed bars only. Require at least two prior tests of a local resistance band, contraction beneath that band, acceptable upper-wick ratio, and trigger close above resistance with `volume_ratio >= min_breakout_volume_ratio`. Stop reference is the contraction low.

- [ ] **Step 4: Implement `MMQ_VWAP_RESET`**

Require a prior qualifying impulse, later VWAP touch/cross, retained gain >= `min_retained_gain`, then a completed-bar reclaim above VWAP with volume/CLV confirmation. Stop reference is the reset low.

- [ ] **Step 5: Implement `MMQ_TRAP_RECLAIM`**

Require an established runner, a completed bar that breaks a recent local low or VWAP and fails to extend, followed by a completed reclaim of the broken level with strong CLV. Stop reference is the trap low.

- [ ] **Step 6: Run focused tests**

Run: `PYTHONPATH=. pytest -q tests/test_merciless_q_strategy.py`

Expected: PASS.

- [ ] **Step 7: Commit**

Commit message: `feat: add Merciless-Q setup variants`

---

### Task 3: Repeated-entry sequencing and cooldown

**Files:**
- Modify: `scanner/strategies/merciless_q/strategy.py`
- Modify: `tests/test_merciless_q_strategy.py`

**Interfaces:**
- Consumes: the four signal detectors from Tasks 1-2.
- Produces: stable repeated Merciless signals with `sequence_number`, `minutes_since_prior_signal`, `runner_age_minutes`, per-variant fresh-reset/cooldown enforcement, and `max_signals_per_symbol` cap.

- [ ] **Step 1: Write failing repeated-entry tests**

```python
def test_repeated_entries_are_sequenced_and_cooled(repeat_runner_bars, runner_context):
    cfg = MercilessConfig(cooldown_bars=3, max_signals_per_symbol=8)
    out = generate_merciless_signals(repeat_runner_bars, runner_context, cfg)
    assert out["sequence_number"].tolist() == list(range(1, len(out) + 1))
    assert out.iloc[1]["minutes_since_prior_signal"] >= 3


def test_repeated_entries_respect_symbol_cap(repeat_runner_bars, runner_context):
    cfg = MercilessConfig(cooldown_bars=1, max_signals_per_symbol=2)
    out = generate_merciless_signals(repeat_runner_bars, runner_context, cfg)
    assert len(out) <= 2
```

- [ ] **Step 2: Run tests and confirm failure**

Run: `PYTHONPATH=. pytest -q tests/test_merciless_q_strategy.py`

Expected: sequence/cooldown tests FAIL.

- [ ] **Step 3: Refactor detection into chronological candidate events**

Each variant detector should return candidate events containing signal index, entry index, stop reference and setup metadata. Merge all events, sort by signal timestamp, then accept chronologically while enforcing:

```python
if signal_idx - last_accepted_idx < cfg.cooldown_bars:
    reject
if same_variant and not fresh_reset_since_last_variant_signal:
    reject
if accepted_count >= cfg.max_signals_per_symbol:
    stop
```

Assign sequence metadata only after acceptance.

- [ ] **Step 4: Run focused tests**

Run: `PYTHONPATH=. pytest -q tests/test_merciless_q_strategy.py`

Expected: PASS.

- [ ] **Step 5: Commit**

Commit message: `feat: sequence repeated Merciless-Q entries`

---

### Task 4: Unified runner integration and Merciless analytics

**Files:**
- Modify: `scripts/run_strategy_research.py`
- Create: `scanner/strategies/merciless_q/reporting.py`
- Create: `tests/test_merciless_q_reporting.py`
- Modify: `tests/test_no_cost_end_to_end.py`

**Interfaces:**
- Consumes: `generate_merciless_signals`, existing replay grid and summary columns.
- Produces: `summarize_merciless_sequences(replays: pd.DataFrame, baseline_slippage_bps: float = 25.0) -> pd.DataFrame`; `merciless_friction_break_even(summary: pd.DataFrame) -> pd.DataFrame`; CLI strategy `merciless`; two new output CSVs.

- [ ] **Step 1: Write failing reporting tests**

```python
def test_sequence_summary_buckets_late_reentries(sample_merciless_replays):
    out = summarize_merciless_sequences(sample_merciless_replays)
    assert set(out["sequence_bucket"]) == {"1", "2", "5+"}


def test_friction_break_even_reports_last_profitable_level(sample_merciless_summary):
    out = merciless_friction_break_even(sample_merciless_summary)
    row = out.iloc[0]
    assert row["last_pf_ge_1_0_bps"] == 50.0
    assert row["last_pf_ge_1_25_bps"] == 25.0
```

- [ ] **Step 2: Add failing runner-selection test**

Assert `_parse_strategies("merciless") == ("merciless",)` and `_parse_strategies("all")` contains `merciless`.

- [ ] **Step 3: Run focused tests and confirm failure**

Run: `PYTHONPATH=. pytest -q tests/test_merciless_q_reporting.py tests/test_no_cost_end_to_end.py`

Expected: FAIL until integration exists.

- [ ] **Step 4: Integrate Merciless generator**

In `generate_price_volume_signals`, register `( "merciless", generate_merciless_signals )`. In `run_research`, include `merciless` in the price-volume study selection and keep the existing dedupe key, which already preserves distinct `entry_timestamp` values.

Update `_parse_strategies` so `all` returns `("orb", "vwap", "merciless", "serclick")` and validation accepts the new key.

- [ ] **Step 5: Implement sequence summary**

Filter `strategy_id == "MERCILESS_Q"` and baseline slippage. Deduplicate replay rows at the signal/rule granularity appropriate for the statistic, derive sequence buckets `1`, `2`, `3`, `4`, `5+`, and summarize n, win rate, PF, expectancy, mean/median peak return and median minutes to peak using available shared replay columns.

- [ ] **Step 6: Implement friction break-even summary**

From shared `strategy_summary.csv` rows for `MERCILESS_Q`, group by variant/direction/split and calculate the highest tested slippage where PF >= 1.0 and PF >= 1.25. Preserve null when no tested slippage meets the threshold.

- [ ] **Step 7: Write output artifacts and news section**

Write:

- `merciless_sequence_summary.csv`
- `merciless_friction_break_even.csv`

in each run output directory and mirror compact latest copies under `data/latest/`. Update `render_news` strategy list and add a Merciless repeat-entry table when non-empty.

- [ ] **Step 8: Run focused tests**

Run: `PYTHONPATH=. pytest -q tests/test_merciless_q_reporting.py tests/test_no_cost_end_to_end.py`

Expected: PASS.

- [ ] **Step 9: Commit**

Commit message: `feat: integrate Merciless-Q research analytics`

---

### Task 5: Documentation, regression tests and verification

**Files:**
- Modify: `README.md`
- Create or modify: `docs/research/merciless_q_methodology.md`
- Modify: `tests/test_documented_configs.py` if configuration documentation checks require it.

**Interfaces:**
- Consumes: completed Merciless-Q code and outputs.
- Produces: runnable documented research command and methodological caveats.

- [ ] **Step 1: Document the strategy family and command**

README must show:

```bash
python scripts/run_strategy_research.py --strategy merciless --feed sip --sessions 60
python scripts/run_strategy_research.py --strategy all --feed sip --sessions 60
```

Document the four V1 variants, repeated-entry analysis, the fact that bar-derived tradability proxies do not reproduce Level-II spread/fill mechanics, and the two new CSV artifacts.

- [ ] **Step 2: Add methodology document**

Explain candidate selection, feature definitions, no-lookahead rules, sequence-number semantics, friction stress, split discipline, and the fact that statistical validation may reject the strategy.

- [ ] **Step 3: Run Merciless focused tests**

Run: `PYTHONPATH=. pytest -q tests/test_merciless_q_strategy.py tests/test_merciless_q_reporting.py`

Expected: PASS.

- [ ] **Step 4: Run full API-free suite**

Run: `PYTHONPATH=. pytest -q`

Expected: all tests PASS.

- [ ] **Step 5: Compile verification**

Run: `python -m compileall -q scanner scripts`

Expected: exit code 0.

- [ ] **Step 6: Commit**

Commit message: `docs: document Merciless-Q research protocol`

- [ ] **Step 7: Open pull request**

Open `feature/merciless-q` into `main` with a body summarizing the four signal variants, repeated-entry/friction artifacts, tests run, and a reminder that historical edge is not claimed until a data-backed research run completes.
