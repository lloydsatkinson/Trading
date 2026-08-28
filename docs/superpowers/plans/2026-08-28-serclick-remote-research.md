# SerClick Remote Research Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the SerClick/Leo research engine remotely on GitHub Actions and emit compact replay, shortlist and news artifacts.

**Architecture:** Keep the audited baseline scanner isolated in `scanner/serclick`, add a deterministic one-minute replay layer and reporting layer, then orchestrate both from a remote pipeline script. GitHub Actions supplies credentials through secrets, runs tests first, caches market data and publishes artifacts.

**Tech Stack:** Python 3.12, pandas, numpy, requests, python-dotenv, pytest, GitHub Actions, Alpaca SIP.

**Spec:** `docs/superpowers/specs/2026-08-28-serclick-remote-research-design.md`

## Global Constraints

- Original Leo thresholds remain unchanged.
- Next-bar entry and 25 bps baseline slippage remain unchanged.
- Morning 09:30-10:30 is observation/trap-building, not preferred execution.
- No credentials or live-order routing in the repository.
- New data from 2026-08-28 onward is the prospective holdout.

---

### Task 1: Import and preserve the audited baseline scanner

**Files:** `scanner/serclick/alpaca_rest.py`, `config.py`, `features.py`, `study.py`, and baseline tests.

**Interfaces:** `SerClickStudy.run() -> dict` plus cached and run CSVs.

- [x] Preserve the existing Leo/state-machine tests.
- [x] Preserve invalid-symbol recovery and project `.env` support.
- [x] Verify imported baseline tests pass.

### Task 2: Add conservative minute-bar replay

**Files:** `scanner/serclick/replay.py`, `tests/test_replay.py`.

**Interfaces:** `simulate_long_trade(...) -> ReplayResult`, `replay_signal_grid(...) -> DataFrame`.

- [x] Write failing tests for same-bar ambiguity, target-before-stop and time exits.
- [x] Verify tests fail because replay module is absent.
- [x] Implement conservative stop-first same-bar ordering and the initial rule grid.
- [x] Verify replay tests pass.

### Task 3: Add variants, metrics and shortlist

**Files:** `scanner/serclick/reporting.py`, `tests/test_reporting.py`.

**Interfaces:** variant filters, profit factor, replay summaries, shortlist and latest JSON.

- [x] Write failing variant/PF/shortlist tests.
- [x] Implement LEO BOTH midday/AH and morning observation variants.
- [x] Implement shortlist actions and compact JSON reporting.
- [x] Verify reporting tests pass.

### Task 4: Replay cached minute data and orchestrate remote pipeline

**Files:** `scanner/serclick/pipeline.py`, `scripts/run_remote_pipeline.py`, `tests/test_pipeline.py`.

- [x] Write failing cache-replay integration test.
- [x] Implement cache replay and variant attachment.
- [x] Implement pipeline orchestration and latest artifacts.
- [x] Verify full unit test suite and compile pass.

### Task 5: Add remote GitHub Actions execution

**Files:** `.github/workflows/serclick-daily.yml`, `.github/workflows/serclick-60d.yml`, `.gitignore`, `requirements.txt`, `README.md`.

- [x] Add daily post-extended-hours workflow with market-data cache.
- [x] Add weekly/manual 60-session workflow with market-data cache.
- [x] Run tests before any API work in both workflows.
- [x] Upload latest news/results and full research output as artifacts.

### Task 6: Remote verification and integration

- [x] Push implementation to isolated branch.
- [x] Open a pull request against `main`.
- [x] Inspect GitHub Actions/check state: PR merge commit passed 12/12 tests and Python compile on GitHub Actions.
- [ ] Merge only after repository-level verification and the one-time Alpaca repository secrets are acknowledged/set.
