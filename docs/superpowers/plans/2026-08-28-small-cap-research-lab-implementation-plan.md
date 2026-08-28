# Small-Cap Research Lab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and maintain a transparent automated tournament for US small-cap long strategies, optimising robust trade frequency and profit factor without final-period leakage.

**Architecture:** Small strategy-rule objects consume signal-time features and share one cost-adjusted metric/tournament layer. Candidate ranking is physically separated from frozen final-period evaluation. CI validates deterministic behaviour; raw datasets and secrets remain outside Git.

**Tech Stack:** Python 3.12, pandas, numpy, pytest, GitHub Actions standard public runners.

**Spec:** `docs/superpowers/specs/2026-08-28-small-cap-research-lab-design.md`

## Global Constraints

- No live order routing.
- No API keys, `.env`, raw CSV/Parquet history, SQLite databases, or broker credentials committed.
- No paid data or paid/larger GitHub runner without explicit cost approval.
- Signal-time features only; outcome columns are never permitted as strategy filters.
- Final-period metrics cannot participate in candidate ranking.
- Costs are deducted before expectancy/PF calculation.
- A failed later regime is recorded as a rejection, not retuned against that same period.

---

### Task 1: Research Package and Signal-Time Features

**Files:**
- Create: `trading_lab/__init__.py`
- Create: `trading_lab/features.py`
- Test: `tests/test_trading_lab.py`

**Interfaces:**
- Produces `add_signal_time_features(frame: pandas.DataFrame) -> pandas.DataFrame`.

- [x] Write a test proving `prior4d = (1 + move_5d) / (1 + move_1d) - 1`.
- [x] Run the test and verify failure before implementation.
- [x] Implement the transformation without reading future-return labels.
- [x] Run tests and verify pass.

### Task 2: Cost-Adjusted Metrics

**Files:**
- Create: `trading_lab/metrics.py`
- Test: `tests/test_trading_lab.py`

**Interfaces:**
- Produces `ReturnMetrics` and `evaluate_returns(returns, roundtrip_cost, trading_days)`.

- [x] Write a failing test with known winners/losses and a 50 bp cost.
- [x] Verify expected failure.
- [x] Implement n, expectancy, PF, win rate and trades/day after costs.
- [x] Verify test and suite pass.

### Task 3: Transparent Rules and Chronological Splits

**Files:**
- Create: `trading_lab/rules.py`
- Create: `trading_lab/splits.py`
- Test: `tests/test_trading_lab.py`

**Interfaces:**
- Produces `RangeRule.mask(frame) -> pandas.Series[bool]`.
- Produces `apply_standard_splits(frame) -> pandas.DataFrame`.

- [x] Test price, momentum, RVOL, dollar-volume, rank and fresh-SEC filtering.
- [x] Test chronological period assignment and post-July exclusion.
- [x] Implement deterministic masks and date splits.
- [x] Run suite.

### Task 4: No-Leakage Tournament

**Files:**
- Create: `trading_lab/tournament.py`
- Test: `tests/test_trading_lab.py`

**Interfaces:**
- Produces `TournamentConfig`.
- Produces `rank_candidates(frame, rules, cfg) -> pandas.DataFrame`.
- Produces `evaluate_frozen_candidate(frame, rule, ...) -> FrozenEvaluation`.

- [x] Test that ranking output has no final-period fields.
- [x] Test that an attractive pre-final candidate collapsing in final is rejected.
- [x] Implement development/validation/hold ranking and physically separate final evaluation.
- [x] Run suite.

### Task 5: Strategy Presets and Research Tournament

**Files:**
- Create/Modify: `trading_lab/presets.py`
- Create: `research/small_cap_runners.md`
- Create/Modify: `research/results_2026-08-28.md`
- Test: `tests/test_trading_lab.py`

**Interfaces:**
- `candidate_strategies() -> list[RangeRule]` returns frozen named hypotheses.

- [x] Freeze `CATALYST_EARLY_RUNNER`.
- [x] Test and add `CATALYST_ROBUST_3_12`.
- [x] Test and add `CATALYST_HF_6_15`.
- [x] Record rejected high-PF rules that collapsed in later regimes.
- [x] Stress candidates at 50–100 bp costs and with winner caps.
- [x] Measure monthly and ticker concentration plus bootstrap uncertainty.

### Task 6: Remote Regression CI

**Files:**
- Create: `.github/workflows/ci.yml`
- Create: `.gitignore`
- Create: `requirements.txt`

- [x] Protect secrets, DBs and raw historical datasets.
- [x] Run Python 3.12 tests on standard `ubuntu-latest`.
- [x] Verify workflow completes successfully on the feature branch.

### Task 7: Intraday Execution Validation

**Files:**
- Future: strategy adapter(s) under `trading_lab/strategies/`
- Future: data-provider adapter(s) using existing SBE/CGFP minute engines.
- Future tests: deterministic minute fixtures plus real-data replay integrity tests.

**Interfaces:**
- Consumes frozen daily research leaders as hypotheses only.
- Produces executable next-open/intraday fills, cost stress, MFE/MAE and forward-paper outcomes.

- [ ] Reuse the recovered SBE/CGFP 1-minute execution machinery without copying raw data to Git.
- [ ] Validate the leader with SIP/Polygon-quality minute history already available to the user, once credentials can be supplied to the execution environment without exposing them.
- [ ] Require a genuinely fresh unseen sample after the already-observed July period.
- [ ] Begin 60-session paper-forward validation before any live recommendation.

### Task 8: Completion Gate

- [ ] Run full local pytest suite.
- [ ] Confirm latest GitHub Actions run succeeds.
- [ ] Confirm no secrets/raw data are committed.
- [ ] Compare feature branch to main and review diff.
- [ ] Open/merge only after verification and keep live trading disabled.
