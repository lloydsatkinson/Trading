# Microcap Pre-Runner Long/Short Implementation Plan

**Goal:** Add a no-lookahead microcap pre-runner research engine to the existing intraday tournament, discover long and short edges separately, optimise transparent thresholds chronologically, and run the study remotely on Alpaca SIP without opening the external August 12-27 holdout.

**Base:** `feat/small-cap-research-lab`

**Target branch:** `feat/microcap-long-short-prerunner`

**Spec:** `docs/superpowers/specs/2026-08-28-microcap-prerunner-long-short-design.md`

## Global constraints

- Research only; no live routing.
- No credentials/raw market history committed.
- No paid data or paid GitHub runners without explicit cost approval.
- Signal-time columns cannot use future bars.
- LONG and SHORT optimisation/reporting remain separate.
- Thresholds are learned from development only; validation rejects; internal test is opened only after freeze.
- August 12-27 remains external untouched data.
- Short PF is not called executable until borrow/locate/fee data exists.

### Task 1 — Snapshot/outcome primitives (TDD)

**Create:** `trading_lab/prerunner.py`
**Test:** `tests/test_prerunner.py`

- [ ] RED: prove a 09:35 spike cannot change the 09:31 snapshot.
- [ ] RED: prove opening RVOL compares exactly the same elapsed 09:30-to-freeze window across prior sessions.
- [ ] RED: prove both long and short MFE/MAE/threshold labels are correct.
- [ ] RED: prove same-minute stop/target ambiguity is stop-first on both sides.
- [ ] RED: prove a gap through a stop exits at the adverse next print rather than the theoretical stop.
- [ ] Implement snapshot preparation, time-normalised RVOL, signal-time structure features, labels and conservative replay.
- [ ] GREEN: run targeted and full suite.

### Task 2 — No-leakage optimiser (TDD)

**Create:** `trading_lab/prerunner_optimizer.py`
**Test:** `tests/test_prerunner_optimizer.py`

- [ ] RED: threshold quantiles ignore validation/test extremes.
- [ ] RED: long and short evaluations cannot be pooled.
- [ ] RED: Pareto frontier removes dominated rules while keeping genuine frequency/PF trade-offs.
- [ ] Implement development-only thresholds, bounded rule combinations, cost stress, PF/expectancy/frequency/drawdown metrics and separate side frontiers.
- [ ] GREEN: run targeted and full suite.

### Task 3 — Unbiased case/control data builder (TDD)

**Modify:** `trading_lab/alpaca_intraday.py`
**Create:** `trading_lab/prerunner_data.py`
**Test:** `tests/test_prerunner_data.py`

- [ ] RED: controls are selected only from prior-close/prior-liquidity information and are unchanged when same-day outcomes are altered.
- [ ] RED: eventual movers can be oversampled as cases without removing deterministic controls.
- [ ] Add prior-volume context, deterministic matched controls and cached opening-history windows for exact RVOL baselines.
- [ ] Preserve existing tournament `prepare()` behaviour; add a separate pre-runner preparation path.
- [ ] GREEN: run full suite.

### Task 4 — Remote research pipeline

**Create:** `scripts/run_prerunner_research.py`
**Create:** `.github/workflows/prerunner-research.yml`
**Modify:** `.github/workflows/ci.yml`

- [ ] Generate 09:25/09:29/09:31/09:32/09:33/09:34/09:35 snapshots.
- [ ] Label future long/short paths and save feature-lift tables.
- [ ] Run development/validation/internal-test optimisation and execution grids.
- [ ] Export separate long and short Pareto frontiers, frozen candidates, rejected rules and limitations.
- [ ] Run tests before remote market-data work.
- [ ] Upload compact artifacts; omit bulky minute cache.

### Task 5 — Research verification

- [ ] Confirm fresh GitHub CI is green.
- [ ] Run the 60-session SIP study ending 2026-08-11.
- [ ] Inspect artifact completeness and failures rather than only workflow status.
- [ ] Report best long/short candidates, sample sizes, trades/day, expectancy, PF, 2x-cost PF and drawdown.
- [ ] Do not open August 12-27 to tune anything.
- [ ] Keep rejected/unstable high-PF rules in the record.

### Task 6 — Integration gate

- [ ] Compare child branch against `feat/small-cap-research-lab`.
- [ ] Confirm no secrets/raw data/live routing.
- [ ] Open PR back to the small-cap research branch after verification.
- [ ] Merge only if CI passes and the research pipeline is reproducible.