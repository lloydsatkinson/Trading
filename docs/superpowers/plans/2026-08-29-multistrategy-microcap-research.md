# Multi-Strategy Microcap Research Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the Trading Research Lab into a shared, mechanically testable ORB, VWAP Momentum/Reclaim and SerClick/Leo research framework for US $50M-$2B equities without changing the locked SerClick baseline.

**Architecture:** Add shared models, no-lookahead intraday features, chronological validation and direction-aware replay. Strategy packages emit one signal schema. A new broad-universe study uses the existing Alpaca client to discover ORB/VWAP candidates independently of Leo, then fetches minute data only for those candidates. The existing `scanner/serclick` package remains operational and is adapted into the shared schema only after parity tests prove its thresholds and entry behaviour are unchanged. Common reporting/ranking compares all strategies under identical execution assumptions.

**Tech Stack:** Python 3.12, pandas >=2.1, numpy >=1.26, requests >=2.31, python-dotenv >=1.0, tabulate >=0.9, pytest >=8.0, GitHub Actions, Alpaca SIP/IEX through the existing client.

**Spec:** `docs/superpowers/specs/2026-08-29-multistrategy-microcap-research-design.md`

## Global Constraints

- Research/backtest/paper validation only; no live order routing.
- Preserve Leo exactly: PM high / prior close > 1.20 and PM dollar turnover > $10M; HOD through 09:59 / prior close > 1.20 and 09:30-09:59 dollar turnover > $5M.
- Preserve SerClick next-executable-one-minute-bar entry and 25 bps baseline slippage.
- Shared slippage scenarios: 10, 25, 50, 75, 100 bps. Signal-bar close fills are forbidden.
- Primary known-cap universe: `50_000_000 <= market_cap < 2_000_000_000`. Unknown historical cap stays `UNKNOWN`; no future backfill.
- Initial price research range: $1-$30.
- Development -> validation -> locked test -> prospective forward is immutable chronological order. Parameter/rule selection uses development + validation only.
- Long and short variants are separate. Short results are signal expectancy unless historical locate availability is known.
- Missing float/news/quotes/halt data stays explicitly unknown.
- Same-minute stop+target ambiguity is resolved against the position.
- Short raw percentage return uses `(entry_price - exit_price) / entry_price`; long raw percentage return uses `(exit_price - entry_price) / entry_price`.
- Market-quality anomalies are risk flags, not claims of manipulation.
- No new paid dependency/service or chargeable run is introduced or triggered by implementation.

---

### Task 1: Shared signal models and chronological validation

**Files:** Create `scanner/core/__init__.py`, `scanner/core/models.py`, `scanner/core/validation.py`, `tests/test_core_models.py`, `tests/test_validation.py`.

**Interfaces:** `SignalRecord.to_dict()`, `market_cap_in_primary_universe()`, `chronological_split()`, `selectable_splits()`.

- [ ] Write failing tests for the $50M lower bound, $300M micro/small boundary, $2B upper bound, UNKNOWN values and required common signal fields.

```python
def test_primary_universe_bounds():
    assert market_cap_in_primary_universe(50_000_000)
    assert market_cap_in_primary_universe(1_999_999_999)
    assert not market_cap_in_primary_universe(49_999_999)
    assert not market_cap_in_primary_universe(2_000_000_000)
```

- [ ] Run `PYTHONPATH=. pytest tests/test_core_models.py -q`; confirm failure because the module is absent.
- [ ] Implement an immutable `SignalRecord` containing strategy/variant/symbol/date/direction/signal timestamp/reference price/next-bar entry prices/stop reference plus market-cap, float, gap, RVOL, time-of-day and catalyst fields with explicit UNKNOWN defaults.
- [ ] Write failing split test proving sessions after development+validation+test become `forward` and `selectable_splits() == ("development", "validation")`.
- [ ] Implement split helpers and run `PYTHONPATH=. pytest tests/test_core_models.py tests/test_validation.py -q`; expect PASS.
- [ ] Commit: `feat: add shared research models and validation`.

---

### Task 2: No-lookahead intraday feature primitives

**Files:** Create `scanner/core/features.py`, `tests/test_core_features.py`.

**Interfaces:** `prepare_intraday_bars`, `opening_range`, `attach_session_vwap`, `rolling_prior_volume_median`, `close_location_value`, gap/RVOL/float/time buckets.

- [ ] Write failing test proving the five-minute opening range includes 09:30-09:34:59 and excludes the 09:35 breakout bar.
- [ ] Write failing test proving a rolling volume baseline excludes the current bar via `shift(1)`.
- [ ] Run `PYTHONPATH=. pytest tests/test_core_features.py -q`; confirm failure.
- [ ] Implement ET timestamps, symbol/session reset, cumulative VWAP using provider VWAP when valid and typical price otherwise, CLV and explicit bucket helpers.
- [ ] Add edge tests for zero-range CLV, missing volume and multiple symbols/dates.
- [ ] Run the feature tests; expect PASS.
- [ ] Commit: `feat: add no-lookahead intraday features`.

---

### Task 3: Direction-aware replay, structural stops, R targets and diagnostics

**Files:** Create `scanner/core/replay.py`, `tests/test_core_replay.py`; modify `scanner/serclick/replay.py`, `tests/test_replay.py`.

**Interfaces:** `ReplayRule`, `ReplayResult`, `apply_entry_slippage`, `simulate_trade`, `replay_signal_grid`. Legacy SerClick imports remain compatible.

- [ ] Write failing tests for long and short same-bar stop+target ambiguity, adverse-direction entry slippage and symmetric raw return.

```python
def test_short_return_is_symmetric_on_entry_not_exit():
    assert raw_return_pct(10.0, 9.0, "SHORT") == 0.10
    assert raw_return_pct(10.0, 10.5, "SHORT") == -0.05
```

- [ ] Run `PYTHONPATH=. pytest tests/test_core_replay.py -q`; confirm failure.
- [ ] Implement percent stop/target replay for LONG and SHORT with conservative intrabar ordering.
- [ ] Add optional `stop_price` and `target_price` overrides so strategy structural levels can be replayed without converting them to future-informed percentages.
- [ ] Add `target_r_multiple` support that derives target from entry-to-stop risk known at entry.
- [ ] Support max holds `(5, 10, 15, 30, 45, 60, 90, 120)` plus an explicit EOD mode bounded by the available regular session/strategy session.
- [ ] Add MFE, MAE, R multiple, bars held and exit reason to `ReplayResult`; write tests for long and short MFE/MAE.
- [ ] Preserve SerClick's public `simulate_long_trade` through a compatibility wrapper and preserve its exact 135-rule default grid.
- [ ] Run `PYTHONPATH=. pytest tests/test_core_replay.py tests/test_replay.py -q`; expect PASS.
- [ ] Commit: `feat: add shared direction-aware trade replay`.

---

### Task 4: Stocks-in-Play 5-minute ORB

**Files:** Create `scanner/strategies/__init__.py`, `scanner/strategies/orb_stocks_in_play/__init__.py`, `config.py`, `strategy.py`, `tests/test_orb_strategy.py`.

**Interface:** `generate_orb_signals(bars, context, cfg=None) -> DataFrame` in common schema.

- [ ] Write failing long breakout test: lock 09:30-09:34 range, require post-09:35 close above OR high, above session VWAP, volume ratio gate, CLV gate, and entry on the next executable minute.
- [ ] Run ORB test and confirm module-not-found failure.
- [ ] Implement active config plus hypothesis grids: gap `(5,8,10,15,20)%`, PM turnover `($1m,$2m,$5m,$10m)`, first-five/opening RVOL `(3,5,10)x`, breakout volume ratio `(1.5,2,3)x`, CLV thresholds `(0.60,0.75)`.
- [ ] Add negative tests for wick-only break, below-VWAP break, low volume and market cap outside $50M-$2B.
- [ ] Implement `ORB_LONG_BREAK`, `ORB_LONG_PULLBACK`, `ORB_SHORT_NEGATIVE_GAP`, `ORB_SHORT_FAILED_GAP` as separate variants; short rows include `borrow_status="UNKNOWN"` unless supplied.
- [ ] Emit structural `stop_reference` from trigger bar/range context and never use bars after the signal to define it.
- [ ] Run `PYTHONPATH=. pytest tests/test_orb_strategy.py -q`; expect PASS.
- [ ] Commit: `feat: add stocks-in-play ORB strategy`.

---

### Task 5: High-RVOL VWAP Momentum/Reclaim

**Files:** Create `scanner/strategies/vwap_momentum/__init__.py`, `config.py`, `strategy.py`, `tests/test_vwap_strategy.py`.

**Interface:** `generate_vwap_signals(bars, context, cfg=None) -> DataFrame` in common schema.

- [ ] Write failing fixture for impulse -> pullback to/cross VWAP -> reclaim close -> next-bar entry.
- [ ] Run VWAP tests and confirm module-not-found failure.
- [ ] Implement grids: gap `(5,10,15,20)%`, impulse `(10,15,20,30)%`, turnover `($2m,$5m,$10m)`, RVOL `(3,5,10)x`, retained gain `(40,60,70,80)%`, reclaim volume ratio `(1.5,2,3)x`.
- [ ] Add failure tests for no VWAP touch, insufficient retained gain, weak reclaim volume and outside-universe cap.
- [ ] Implement `VWAP_LONG_RECLAIM` and `VWAP_SHORT_REJECTION`; short rows preserve unknown borrow status.
- [ ] Emit structural stop from reclaim/rejection swing known at signal time; optionally tag rising five-minute VWAP slope/high-quality variant without making it mandatory in the base variant.
- [ ] Run `PYTHONPATH=. pytest tests/test_vwap_strategy.py -q`; expect PASS.
- [ ] Commit: `feat: add high-rvol VWAP momentum strategy`.

---

### Task 6: SerClick/Leo shared-schema adapter with parity protection

**Files:** Create `scanner/strategies/serclick_leo/__init__.py`, `config.py`, `strategy.py`, `tests/test_serclick_adapter.py`.

**Interface:** `adapt_serclick_ignitions(ignitions) -> DataFrame`.

- [ ] Write failing test locking extension ratio 1.20, PM turnover $10M and open-30 turnover $5M.
- [ ] Write mapping test proving adapter preserves source `entry_timestamp` and `entry_price_slipped` exactly.
- [ ] Implement a thin adapter only; do not reimplement the SerClick state machine.
- [ ] Map morning to `MORNING_OBSERVATION`, BOTH 10:30-15:00 to `LEO_BOTH_MIDDAY`, BOTH 16:00-20:00 to `LEO_BOTH_AH`.
- [ ] Run legacy `tests/test_features.py tests/test_reporting.py` plus adapter tests; expect PASS.
- [ ] Commit: `feat: adapt SerClick signals to shared schema`.

---

### Task 7: Broad-universe ORB/VWAP candidate discovery independent of Leo

**Files:** Create `scanner/multistrategy/__init__.py`, `scanner/multistrategy/config.py`, `scanner/multistrategy/study.py`, `tests/test_multistrategy_study.py`.

**Interfaces:** `MultiStrategyStudy._daily_bars`, `_prior_close_map`, `_fetch_early_day`, `_broad_candidate_context`, `_opening_baseline`, `_fetch_minute_day`, `run() -> dict`.

- [ ] Write a failing unit test showing a +10% gap/$2M PM-turnover symbol that does **not** satisfy Leo's +20% extension can still become an ORB/VWAP research candidate.
- [ ] Reuse `AlpacaCredentials`, `AlpacaRest`, asset filtering and calendar logic; do not fork credentials/network code.
- [ ] Broad prefilter uses the least restrictive values from approved research grids (e.g. abs gap >=5% and qualifying activity) so later parameter grids do not suffer selection bias from a tighter upstream gate.
- [ ] Build a 20-session opening-window baseline cache for candidate symbols; compute first-five-minute volume/dollar-turnover RVOL against **prior** same-window observations only. Current-day opening data must not enter its own baseline.
- [ ] Fetch one-minute data only after broad prefiltering to control API volume.
- [ ] Candidate context includes prior close, PM high/low/volume/turnover/gap, opening five-minute turnover/RVOL, market-cap snapshot fields, and float/news fields only when genuinely available.
- [ ] Market-cap snapshots remain prospective/date-valid exactly as current `marketcap.py`; unknown historical market cap is retained instead of backfilled.
- [ ] Write tests that current-day opening volume cannot leak into the historical baseline and that missing float/news remains UNKNOWN.
- [ ] Run `PYTHONPATH=. pytest tests/test_multistrategy_study.py -q`; expect PASS using mocked/local data only.
- [ ] Commit: `feat: add independent multi-strategy candidate study`.

---

### Task 8: Common reporting, slippage resilience and auditable ranking

**Files:** Create `scanner/core/reporting.py`, `scanner/portfolio/__init__.py`, `scanner/portfolio/strategy_ranker.py`, `tests/test_core_reporting.py`, `tests/test_strategy_ranker.py`.

**Interfaces:** `profit_factor`, `summarize_strategy_replays`, `slippage_resilience`, `rank_strategies`.

- [ ] Write failing test where a bad validation rule has spectacular forward returns; assert it cannot outrank the validation winner during selection.
- [ ] Write failing slippage test: PF sequence 1.8/1.4/1.1/0.9 at 10/25/50/75 bps yields first PF<1.2 at 50 bps and PF<1.0 at 75 bps.
- [ ] Implement n, trades/day, expectancy, median return, win rate, PF, mean/median R, MFE, MAE, sequential max drawdown, £1,000 position economics, strategy/variant/direction/cap bucket/slippage fields.
- [ ] Add eligibility flags for n>=20, n>=50, n>=100.
- [ ] Implement auditable robustness components for validation PF/expectancy/log-n/median/drawdown/slippage resilience; nearby-parameter and subgroup stability contribute only when available, with component columns retained.
- [ ] Test market-cap, gap, RVOL, float, time-of-day and direction segmentation without pooling shorts with longs.
- [ ] Run reporting/ranker tests; expect PASS.
- [ ] Commit: `feat: add cross-strategy research ranking`.

---

### Task 9: Multi-strategy runner and five-scenario replay

**Files:** Create `scripts/run_strategy_research.py`, `tests/test_strategy_runner.py`; minimally modify `scanner/serclick/pipeline.py` only if a cache-reading helper can be shared without changing its behaviour.

**CLI:** `python scripts/run_strategy_research.py --strategy all --feed sip --sessions 60 --end-date YYYY-MM-DD --root . [--cache-only]`.

**Outputs:** `data/research/multistrategy/<run_id>/signals.csv`, `replay_grid.csv`, `strategy_summary.csv`, `leaderboard.csv`, `slippage_summary.csv`, `run_meta.json`, with compact mirrors under `data/latest/`.

- [ ] Write failing cache-only integration test with temporary daily/early/minute/opening-baseline files; no network/API is used by the test.
- [ ] Implement registry keys `orb`, `vwap`, `serclick`, `all` and common signal concatenation.
- [ ] In normal mode, orchestrate `MultiStrategyStudy`; in `--cache-only`, refuse missing required cache rather than silently calling the network.
- [ ] Replay each signal at 10/25/50/75/100 bps. Preserve SerClick's original 25-bps entry as the compatibility reference while other slippage rows are explicit scenario replays.
- [ ] Replay approved percent stops/targets, structural stops and R-target variants, including max-hold table through EOD.
- [ ] Generate skip-reason records when required context is unavailable rather than inventing RVOL/float/news.
- [ ] Run `PYTHONPATH=. pytest tests/test_strategy_runner.py tests/test_pipeline.py -q`; expect PASS.
- [ ] Commit: `feat: add multi-strategy research runner`.

---

### Task 10: Documentation and API-free CI coverage

**Files:** Modify `README.md`, `.github/workflows/ci.yml`; create `docs/research/multistrategy_methodology.md`, `tests/test_documented_configs.py`.

- [ ] Add parity test for `DEFAULT_SLIPPAGE_BPS == (10, 25, 50, 75, 100)` and documented cap boundaries.
- [ ] Add implementation branch `multistrategy-microcap-research-v1` to CI push branches; retain PR-to-main tests.
- [ ] Keep CI API-free: install dependencies, `pytest -q`, `python -m compileall -q scanner scripts`; do not run the market-data study automatically.
- [ ] Document evidence states `HYPOTHESIS`, `VALIDATED`, `LOCKED_TEST`, `FORWARD` and that small-n high PF is insufficient for promotion.
- [ ] Document local commands including `--cache-only`; state normal research mode can consume the user's existing Alpaca entitlement and is not invoked automatically.
- [ ] Run full test suite and compile; expect zero failures/errors.
- [ ] Commit: `docs: document multi-strategy research workflow`.

---

### Task 11: Repository verification, PR and merge gate

**Files:** All Task 1-10 changes.

- [ ] Run `PYTHONPATH=. pytest -q` and `python -m compileall -q scanner scripts` from a clean checkout/branch state.
- [ ] Confirm legacy SerClick tests still lock 1.20 extension, $10M PM, $5M open-30, conservative same-bar behaviour and 135-rule legacy grid.
- [ ] Inspect diff vs `main`; ensure no `.env`, API keys, cached data, research artifacts, databases or live-order code.
- [ ] Open PR `Add multi-strategy microcap research framework` from `multistrategy-microcap-research-v1` to `main`; body explicitly says no paid remote research run was triggered.
- [ ] Inspect GitHub CI. For any failure, reproduce the smallest failing test, fix via TDD and push a corrective commit.
- [ ] Merge only when CI is green and merge itself creates no new cost.
- [ ] Do **not** trigger the full Alpaca/GitHub Actions research run under standing approval because it may consume metered resources; that remains the cost boundary.
