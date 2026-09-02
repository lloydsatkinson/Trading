# Unified Real-Time Scanner Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the API-free core of the unified real-time scanner so ORB, VWAP and SerClick/Leo can be evaluated from one point-in-time state, gated by authoritative research evidence, lifecycle-managed, consensus-ranked and written idempotently to a forward-test ledger.

**Architecture:** Add a focused `scanner/live/` package above the existing batch research code. Extract trigger decisions from ORB/VWAP so both batch and live paths call the same no-lookahead decision logic; wrap SerClick by running its existing `analyze_candidate_day` on bar prefixes and consuming its transition output. Prove the entire path with a deterministic fake stream before adding any real market-data transport.

**Tech Stack:** Python 3.12 (matching `.github/workflows/ci.yml`), standard-library `dataclasses`, `enum`, `hashlib`, `sqlite3`, `zoneinfo`; pandas; NumPy; pytest.

**Spec:** `docs/superpowers/specs/2026-09-02-unified-realtime-scanner-v1-design.md`

## Global Constraints

- No live broker order routing in Phase 1.
- Completed one-minute bars are the default decision clock.
- All session logic uses timezone-aware `America/New_York` timestamps.
- `scanner.portfolio.strategy_ranker.rank_strategies(..., production_min_expectancy=0.05)` remains the authoritative production gate.
- A strategy missing from the authoritative leaderboard defaults to research-only.
- `RESEARCH`, `VALIDATION`, `LOCKED_TEST`, and `FORWARD_ONLY` signals may be measured but never appear as unlabeled production `FIRE`.
- `STALE`, `DISCONNECTED`, and `RECOVERING` feed states block new production FIRE events.
- Unknown catalyst/float/fundamental fields remain explicit `UNKNOWN`.
- Consensus uses diminishing weight inside one correlation group and full weight only across independent groups.
- Strong opposite-direction evidence surfaces `CONFLICT`.
- Signal events are immutable and append-only; SQLite writes are idempotent by stable event ID.
- Existing public batch APIs and existing research tests stay green.
- No API credential, cached market data, SQLite DB, or generated forward artifact is committed.

## Phase 1 File Map

Create:

```text
scanner/live/
├── __init__.py
├── models.py
├── clock.py
├── feed_health.py
├── symbol_state.py
├── feature_engine.py
├── strategy_registry.py
├── lifecycle.py
├── signal_bus.py
├── consensus.py
├── ranker.py
├── forward_ledger.py
├── fake_stream.py
├── service.py
└── adapters/
    ├── __init__.py
    ├── orb.py
    ├── vwap.py
    └── serclick_leo.py

tests/live/
├── test_models_clock.py
├── test_feed_health.py
├── test_symbol_state_features.py
├── test_strategy_registry.py
├── test_lifecycle.py
├── test_consensus_ranker.py
├── test_forward_ledger.py
├── test_orb_live_parity.py
├── test_vwap_live_parity.py
├── test_serclick_live_parity.py
└── test_live_service_end_to_end.py
```

Modify only where parity requires it:

```text
scanner/core/models.py
scanner/strategies/orb_stocks_in_play/strategy.py
scanner/strategies/vwap_momentum/strategy.py
scanner/strategies/serclick_leo/strategy.py
README.md
docs/research/unified_live_scanner_phase1.md
```

---

### Task 1: Live immutable models, stable IDs, session clock, and feed health

**Files:**
- Create: `scanner/live/__init__.py`
- Create: `scanner/live/models.py`
- Create: `scanner/live/clock.py`
- Create: `scanner/live/feed_health.py`
- Test: `tests/live/test_models_clock.py`
- Test: `tests/live/test_feed_health.py`

**Interfaces:**
- `Direction`, `MarketSession`, `LifecycleState`, `ProductionStatus`, `FeedHealth` as `StrEnum` values using the exact strings in the approved spec.
- Frozen dataclasses `MarketBar`, `FeatureSnapshot`, `StrategyDescriptor`, `StrategyIntent`, `LiveSignalEvent`.
- `stable_signal_id(strategy_id, variant_id, symbol, direction, setup_anchor, strategy_version) -> str`.
- `stable_event_id(signal_id, state, event_timestamp) -> str`.
- `SessionClock.classify(ts)`, `is_operating(ts)`, `session_date(ts)`.
- `FeedHealthMonitor.connect()`, `observe_event(event_ts, now)`, `disconnect()`, `begin_recovery()`, `mark_recovered()`.

- [ ] **Step 1: Write RED tests for immutable bars and stable IDs**

Use this exact assertion shape in `tests/live/test_models_clock.py`:

```python
from dataclasses import FrozenInstanceError
from datetime import datetime
from zoneinfo import ZoneInfo
import pytest

from scanner.live.models import Direction, LifecycleState, MarketBar, stable_event_id, stable_signal_id

ET = ZoneInfo("America/New_York")


def test_market_bar_is_frozen_and_ids_are_deterministic():
    ts = datetime(2026, 9, 2, 9, 35, tzinfo=ET)
    bar = MarketBar("ABC", ts, 4.0, 4.3, 3.9, 4.2, 100_000)
    with pytest.raises(FrozenInstanceError):
        bar.close = 9.0
    first = stable_signal_id("ORB", "ORB_LONG_BREAK", "ABC", Direction.LONG, ts, "orb-v1")
    second = stable_signal_id("ORB", "ORB_LONG_BREAK", "ABC", Direction.LONG, ts, "orb-v1")
    assert first == second
    assert stable_event_id(first, LifecycleState.FIRE, ts) == stable_event_id(first, LifecycleState.FIRE, ts)
```

- [ ] **Step 2: Write RED session-clock tests**

Assert 08:00 ET = PREMARKET, 10:00 ET = REGULAR, 17:00 ET = AFTER_HOURS, 21:00 ET = CLOSED. Also pass `2026-09-02 13:35 UTC` and require REGULAR after timezone conversion. Naive datetime input must raise `ValueError`.

- [ ] **Step 3: Write RED feed-health tests**

With `delayed_after_seconds=15`, `stale_after_seconds=90`:
- `connect()` -> RECOVERING;
- a 20-second-old event -> DELAYED;
- a 100-second-old event -> STALE;
- `disconnect()` -> DISCONNECTED;
- `begin_recovery()` -> RECOVERING;
- `mark_recovered()` before observing a fresh event raises `RuntimeError`;
- after observing a fresh event, `mark_recovered()` -> LIVE.

- [ ] **Step 4: Run tests and verify RED**

```bash
PYTHONPATH=. pytest -q tests/live/test_models_clock.py tests/live/test_feed_health.py
```

- [ ] **Step 5: Implement exact model fields**

`MarketBar`: `symbol`, `timestamp`, `open`, `high`, `low`, `close`, `volume`.

`FeatureSnapshot`: `symbol`, `timestamp`, `session`, `last_price`, `session_vwap`, `hod`, `lod`, `gap_pct`, `rvol`, `volume_acceleration`, `spread_pct`, `catalyst_class`, `market_cap_bucket`, `float_bucket`, `time_of_day_bucket`, `context`.

`StrategyDescriptor`: `strategy_id`, `strategy_family`, `variant_id`, `direction`, `strategy_version`, `production_status`, `production_eligible`, `correlation_group`, `evidence_score`, `required_features`.

`StrategyIntent`: `descriptor`, `symbol`, `state`, `event_timestamp`, `setup_anchor`, `reference_price`, `setup_score`, `execution_score`, `reason_codes`, `explanation`, `entry_trigger`, `stop_reference`, `target_1`, `target_2`, `management_policy`, `metadata`.

`LiveSignalEvent`: `event_id`, `signal_id`, `intent`, `effective_state`, `action_label`, `feed_health`, `source_timestamp`.

Stable IDs use SHA-256 over pipe-separated canonical fields and truncate to 24 hex chars.

- [ ] **Step 6: Implement clock and health rules exactly as tested**

Clock ranges: 04:00-09:29:59 PREMARKET; 09:30-15:59:59 REGULAR; 16:00-19:59:59 AFTER_HOURS; otherwise CLOSED.

- [ ] **Step 7: Run targeted regression**

```bash
PYTHONPATH=. pytest -q tests/live/test_models_clock.py tests/live/test_feed_health.py tests/test_core_models.py
```

- [ ] **Step 8: Commit**

```bash
git add scanner/live tests/live/test_models_clock.py tests/live/test_feed_health.py
git commit -m "feat: add live scanner models clock and health"
```

---

### Task 2: Bounded symbol state and shared point-in-time feature engine

**Files:**
- Create: `scanner/live/symbol_state.py`
- Create: `scanner/live/feature_engine.py`
- Test: `tests/live/test_symbol_state_features.py`

**Interfaces:**
- `SymbolState(symbol, max_bars=600)`.
- `append_bar(bar)`, `bars_frame()`, `latest`.
- `SymbolStateStore.get(symbol) -> SymbolState`.
- `FeatureEngine.snapshot(state, context) -> FeatureSnapshot`.

- [ ] **Step 1: Write RED state-ordering tests**

Construct four sequential `MarketBar` values at 09:30-09:33 ET with `max_bars=3`. Require only the last three bars remain. Require `ValueError` for a different symbol, a naive timestamp, or a timestamp less than/equal to the latest stored timestamp.

- [ ] **Step 2: Write RED feature test with exact known inputs**

Use three bars:

```text
09:30 O=4.00 H=4.20 L=3.95 C=4.10 V=100
09:31 O=4.10 H=4.30 L=4.05 C=4.20 V=200
09:32 O=4.20 H=4.40 L=4.15 C=4.35 V=400
```

Context:

```python
{
    "prior_close": 4.0,
    "opening_rvol": 8.0,
    "market_cap": 120_000_000,
    "float_shares": 8_000_000,
    "catalyst_class": "EARNINGS",
}
```

Require HOD=4.40, LOD=3.95, RVOL=8.0, catalyst `EARNINGS`, and a finite session VWAP. Future bars must not be present in the DataFrame used to calculate the snapshot.

- [ ] **Step 3: Run RED**

```bash
PYTHONPATH=. pytest -q tests/live/test_symbol_state_features.py
```

- [ ] **Step 4: Implement bounded state**

Store immutable `MarketBar` values in a `collections.deque(maxlen=max_bars)`. `bars_frame()` returns columns compatible with existing research helpers: `symbol`, `timestamp_et`, `session_date`, `open`, `high`, `low`, `close`, `volume`.

- [ ] **Step 5: Implement shared features using existing helpers**

Reuse `scanner.core.features.attach_session_vwap`, `bucket_float`, `bucket_gap`, `bucket_rvol`, `bucket_time_of_day`; do not duplicate those formulas.

Volume acceleration is:

```text
latest completed bar volume / median(previous up to 5 completed bar volumes)
```

when there are at least two previous bars and the median is positive; otherwise `None`.

`opening_rvol` comes from point-in-time context in Phase 1; if unavailable set `rvol=None`.

- [ ] **Step 6: Run feature regressions**

```bash
PYTHONPATH=. pytest -q tests/live/test_symbol_state_features.py tests/test_core_features.py tests/test_features.py
```

- [ ] **Step 7: Commit**

```bash
git add scanner/live/symbol_state.py scanner/live/feature_engine.py tests/live/test_symbol_state_features.py
git commit -m "feat: add live symbol state and shared features"
```

---

### Task 3: Strategy registry, authoritative production evidence, lifecycle, and signal bus

**Files:**
- Create: `scanner/live/strategy_registry.py`
- Create: `scanner/live/lifecycle.py`
- Create: `scanner/live/signal_bus.py`
- Test: `tests/live/test_strategy_registry.py`
- Test: `tests/live/test_lifecycle.py`

**Interfaces:**
- `LiveStrategyAdapter` protocol with `descriptor` property and `evaluate(state, features, prior_event) -> StrategyIntent | None`.
- `StrategyRegistry.from_leaderboard(adapters, leaderboard)`.
- `LifecycleEngine.apply(intent, feed_health) -> LiveSignalEvent | None`.
- `SignalBus.subscribe(callback)`, `publish(event)`.

- [ ] **Step 1: Write RED authoritative-gate test**

Create a local test adapter whose descriptor claims high setup quality but whose exact `(strategy_id="ORB", variant_id="ORB_LONG_BREAK", direction="LONG")` leaderboard row has `production_eligible=False`, `robustness_score=0.91`. Require registry output `production_eligible=False`, `production_status=RESEARCH`, `evidence_score=91.0`.

Add a second row with `production_eligible=True` and require `PRODUCTION_ELIGIBLE`. Missing rows remain RESEARCH.

- [ ] **Step 2: Write RED lifecycle test with explicit descriptors/intents**

Construct a `StrategyDescriptor` directly in the test, then construct `StrategyIntent` values for WATCH -> ARMED -> FIRE using the same `setup_anchor`. Require:
- duplicate WATCH returns `None`;
- backwards ARMED -> WATCH raises `ValueError`;
- production LONG FIRE label is `FIRE LONG`;
- non-production FIRE label is `RESEARCH FIRE`;
- attempted production FIRE under STALE becomes `DATA_DEGRADED` / `DATA DEGRADED`.

- [ ] **Step 3: Run RED**

```bash
PYTHONPATH=. pytest -q tests/live/test_strategy_registry.py tests/live/test_lifecycle.py
```

- [ ] **Step 4: Implement exact adapter protocol and leaderboard matching**

Match on strategy ID + variant ID + direction. Convert `robustness_score` 0-1 to evidence score 0-100. Never inspect test/forward results to change eligibility.

- [ ] **Step 5: Implement transition table**

Allowed progression:

```text
DISCOVER -> WATCH | ARMED | INVALIDATED | EXPIRED
WATCH -> ARMED | INVALIDATED | EXPIRED | DATA_DEGRADED | HALTED
ARMED -> FIRE | INVALIDATED | EXPIRED | DATA_DEGRADED | HALTED
FIRE -> MANAGE | EXIT | INVALIDATED | DATA_DEGRADED | HALTED
MANAGE -> EXIT | INVALIDATED | DATA_DEGRADED | HALTED
DATA_DEGRADED -> WATCH | ARMED | INVALIDATED | EXPIRED
HALTED -> WATCH | ARMED | INVALIDATED | EXPIRED
```

A new setup gets a new stable signal ID; do not reset an existing signal backwards.

- [ ] **Step 6: Implement synchronous signal bus**

Fan out each event once. If one subscriber fails, still call remaining subscribers, then raise `SignalDispatchError` containing all subscriber errors.

- [ ] **Step 7: Run regressions**

```bash
PYTHONPATH=. pytest -q tests/live/test_strategy_registry.py tests/live/test_lifecycle.py tests/test_strategy_ranker.py
```

- [ ] **Step 8: Commit**

```bash
git add scanner/live/strategy_registry.py scanner/live/lifecycle.py scanner/live/signal_bus.py tests/live/test_strategy_registry.py tests/live/test_lifecycle.py
git commit -m "feat: add live strategy gating and lifecycle"
```

---

### Task 4: Correlation-aware consensus and live 0-100 ranking

**Files:**
- Modify: `scanner/live/models.py` to add `ConsensusSnapshot` and `RankedOpportunity`.
- Create: `scanner/live/consensus.py`
- Create: `scanner/live/ranker.py`
- Test: `tests/live/test_consensus_ranker.py`

**Interfaces:**
- `build_consensus(events) -> dict[(symbol, direction), ConsensusSnapshot]`.
- `rank_event(event, features, consensus) -> float`.
- `rank_active(events, features_by_symbol) -> list[RankedOpportunity]`.

- [ ] **Step 1: Write RED same-group versus independent-group test**

Create three concrete `LiveSignalEvent` objects in the test using descriptors:
- ORB_LONG_BREAK correlation `ORB`, setup 80;
- ORB_LONG_PULLBACK correlation `ORB`, setup 80;
- VWAP_LONG_RECLAIM correlation `VWAP`, setup 80.

Require consensus(ORB break + VWAP reclaim) > consensus(ORB break + ORB pullback).

- [ ] **Step 2: Write RED conflict test**

Create one active LONG ARMED/FIRE and one active SHORT ARMED/FIRE on the same symbol from different families. Require both direction snapshots `conflict=True`, `confidence_label="CONFLICT"`.

- [ ] **Step 3: Write RED score formula test**

Use the exact approved weights:

```python
expected = (
    0.35 * evidence
    + 0.20 * setup
    + 0.15 * participation
    + 0.10 * catalyst
    + 0.10 * consensus
    + 0.05 * execution
    + 0.05 * regime
)
```

Clamp each component and final score to 0-100. Unknown catalyst = neutral 50. Conflict = 20-point post-composition penalty. STALE/DISCONNECTED/RECOVERING caps visible score at 49 but lifecycle remains responsible for blocking FIRE.

- [ ] **Step 4: Run RED**

```bash
PYTHONPATH=. pytest -q tests/live/test_consensus_ranker.py
```

- [ ] **Step 5: Implement diminishing correlation-group multipliers**

Within one group sort strongest first and use multipliers `1.00`, `0.35`, then `0.15` for every additional variant. Independent groups each receive a new 1.00 contribution.

Confidence labels:
- one active family: `SINGLE_EDGE`;
- two independent active families: `CONFIRMED`;
- three or more independent active families: `MULTI_EDGE`;
- opposing active direction: `CONFLICT`.

- [ ] **Step 6: Implement participation and regime inputs without fabrication**

Participation uses known RVOL and volume acceleration; if neither is known, neutral 50. Regime score comes from adapter metadata only when validated; otherwise neutral 50.

- [ ] **Step 7: Run tests and commit**

```bash
PYTHONPATH=. pytest -q tests/live/test_consensus_ranker.py
git add scanner/live/models.py scanner/live/consensus.py scanner/live/ranker.py tests/live/test_consensus_ranker.py
git commit -m "feat: add consensus-aware live ranking"
```

---

### Task 5: Idempotent SQLite forward ledger and restart state

**Files:**
- Create: `scanner/live/forward_ledger.py`
- Test: `tests/live/test_forward_ledger.py`
- Modify: `.gitignore` only if `data/live/*.db` is not already covered.

**Interfaces:**
- `ForwardLedger(path)`.
- `append_event(event, features) -> bool` returns `True` only on first insert.
- `append_health(timestamp, state, details) -> bool`.
- `latest_events(session_date) -> list[LiveSignalEvent]`.
- `event_count() -> int`.

- [ ] **Step 1: Write RED idempotency test**

Construct one concrete frozen descriptor, FIRE intent and LiveSignalEvent directly in the test. Call `append_event` twice with the identical event and require returns `True`, then `False`, and total count 1.

- [ ] **Step 2: Write RED restart test**

Close the first ledger, open a new `ForwardLedger` on the same path, call `latest_events(date(2026, 9, 2))`, and require the reconstructed event preserves `event_id`, `signal_id`, strategy/variant, direction, effective state and action label.

- [ ] **Step 3: Run RED**

```bash
PYTHONPATH=. pytest -q tests/live/test_forward_ledger.py
```

- [ ] **Step 4: Implement SQLite schema**

```sql
CREATE TABLE IF NOT EXISTS signal_events (
    event_id TEXT PRIMARY KEY,
    signal_id TEXT NOT NULL,
    strategy_id TEXT NOT NULL,
    variant_id TEXT NOT NULL,
    strategy_version TEXT NOT NULL,
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL,
    event_timestamp TEXT NOT NULL,
    setup_anchor TEXT NOT NULL,
    effective_state TEXT NOT NULL,
    action_label TEXT NOT NULL,
    production_status TEXT NOT NULL,
    production_eligible INTEGER NOT NULL,
    reference_price REAL NOT NULL,
    entry_trigger REAL,
    stop_reference REAL,
    target_1 REAL,
    target_2 REAL,
    setup_score REAL NOT NULL,
    evidence_score REAL NOT NULL,
    execution_score REAL NOT NULL,
    feed_health TEXT NOT NULL,
    feature_json TEXT NOT NULL,
    reason_codes_json TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    inserted_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scanner_health (
    health_id TEXT PRIMARY KEY,
    event_timestamp TEXT NOT NULL,
    state TEXT NOT NULL,
    details_json TEXT NOT NULL
);
```

Use `INSERT OR IGNORE` and stable IDs. Serialize JSON with `sort_keys=True`, `default=str`; do not pickle.

- [ ] **Step 5: Run tests and commit**

```bash
PYTHONPATH=. pytest -q tests/live/test_forward_ledger.py
git add scanner/live/forward_ledger.py tests/live/test_forward_ledger.py .gitignore
git commit -m "feat: add idempotent forward ledger"
```

---

### Task 6: Extract ORB/VWAP no-lookahead trigger decisions and prove batch/live parity

**Files:**
- Modify: `scanner/core/models.py`
- Modify: `scanner/strategies/orb_stocks_in_play/strategy.py`
- Modify: `scanner/strategies/vwap_momentum/strategy.py`
- Create: `scanner/live/adapters/__init__.py`
- Create: `scanner/live/adapters/orb.py`
- Create: `scanner/live/adapters/vwap.py`
- Test: `tests/live/test_orb_live_parity.py`
- Test: `tests/live/test_vwap_live_parity.py`

**Interfaces:**
- Add frozen `TriggerDecision(variant_id, direction, signal_timestamp, reference_price, stop_reference, setup_metadata)` to `scanner/core/models.py`.
- `detect_orb_triggers(bars, context, cfg=None) -> list[TriggerDecision]`.
- `detect_vwap_triggers(bars, context, cfg=None) -> list[TriggerDecision]`.
- Preserve public signatures `generate_orb_signals(...)` and `generate_vwap_signals(...)`.
- Add `ORBLiveAdapter` and `VWAPLiveAdapter` implementing `LiveStrategyAdapter`.

- [ ] **Step 1: Freeze existing behavior before refactor**

Run:

```bash
PYTHONPATH=. pytest -q tests/test_orb_strategy.py tests/test_no_cost_vwap_end_to_end.py
```

Existing ORB fixtures already lock:
- `long_breakout_fixture()` -> ORB_LONG_BREAK signal 09:36, next-bar entry 09:37, structural stop 5.30;
- negative-gap short -> ORB_SHORT_NEGATIVE_GAP;
- pullback -> ORB_LONG_PULLBACK;
- failed positive-gap reversal -> ORB_SHORT_FAILED_GAP.

Existing VWAP smoke fixtures already lock `VWAP_LONG_RECLAIM` and `VWAP_SHORT_REJECTION` through the real research path.

- [ ] **Step 2: Write RED ORB prefix-parity test using the exact rows from `tests/test_orb_strategy.py::long_breakout_fixture`**

Duplicate those exact eight rows into `tests/live/test_orb_live_parity.py` rather than importing another test module. Use the exact `valid_context()` values and ORBConfig thresholds from `test_orb_long_requires_locked_range_and_enters_next_bar`.

Batch truth:

```python
batch = generate_orb_signals(full_bars, context, cfg)
truth = batch[batch["variant_id"].eq("ORB_LONG_BREAK")].iloc[0]
```

Live loop: append each completed bar to `SymbolState`, build one `FeatureSnapshot`, call `ORBLiveAdapter.evaluate`. Require no FIRE before `truth.signal_timestamp`; first FIRE timestamp/variant/direction/stop must equal batch truth.

- [ ] **Step 3: Write RED VWAP prefix-parity tests using the exact `_long_bars()` and `_short_bars()` rows from `tests/test_no_cost_vwap_end_to_end.py`**

Use the same context values. Require parity for variant, direction, trigger timestamp and structural stop. Require no early FIRE.

- [ ] **Step 4: Run RED**

```bash
PYTHONPATH=. pytest -q tests/live/test_orb_live_parity.py tests/live/test_vwap_live_parity.py
```

- [ ] **Step 5: Extract ORB trigger detection without future-bar access**

Move the existing breakout/pullback/failed-gap/negative-gap decision conditions into `detect_orb_triggers`. The detector may inspect only the supplied prefix and must not access `idx + 1`.

`generate_orb_signals` then converts each decision into the existing `SignalRecord` only when the next executable same-session bar exists. This preserves historical next-bar execution while letting live mode know a trigger immediately after its completed signal bar.

- [ ] **Step 6: Extract VWAP trigger detection using the same pattern**

Do not change thresholds or setup definitions. Batch generator continues using next-bar entry/slippage; live detector never requires next-bar data.

- [ ] **Step 7: Implement thin live adapters**

For each completed bar:
- call `detect_*_triggers(state.bars_frame(), features.context)`;
- consider only a decision whose `signal_timestamp == state.latest.timestamp`;
- return a FIRE `StrategyIntent` for a newly detected trigger;
- take production status/evidence from the descriptor supplied by registry, never from strategy code;
- use decision structural stop and reference price;
- do not add new thresholds.

- [ ] **Step 8: Run parity and existing regressions**

```bash
PYTHONPATH=. pytest -q \
  tests/live/test_orb_live_parity.py \
  tests/live/test_vwap_live_parity.py \
  tests/test_orb_strategy.py \
  tests/test_no_cost_vwap_end_to_end.py \
  tests/test_no_cost_end_to_end.py
```

- [ ] **Step 9: Commit**

```bash
git add scanner/core/models.py scanner/strategies/orb_stocks_in_play/strategy.py scanner/strategies/vwap_momentum/strategy.py scanner/live/adapters tests/live/test_orb_live_parity.py tests/live/test_vwap_live_parity.py
git commit -m "refactor: share ORB and VWAP triggers with live scanner"
```

---

### Task 7: SerClick/Leo prefix adapter and ignition parity

**Files:**
- Create: `scanner/live/adapters/serclick_leo.py`
- Test: `tests/live/test_serclick_live_parity.py`
- Modify: `scanner/strategies/serclick_leo/strategy.py` only if a small public normalization helper is needed.

**Interfaces:**
- Reuse `scanner.serclick.features.analyze_candidate_day(prefix_bars, qualification, cfg)`.
- Consume SerClick `transitions` for immediate states; do not use future-dependent event entry fields to decide FIRE timing.
- Reuse `_variant` behavior through a public helper if required rather than duplicating time-window mapping.

- [ ] **Step 1: Write RED test proving ignition can be observed from transition output before next-bar entry exists**

Use a synthetic candidate with a permissive test-only `SerClickConfig` to force the existing state machine through SHORTS_BUILDING -> ABSORPTION -> ARMED -> IGNITION. Lower only config thresholds in the test; do not alter production defaults. The test must first prove the full bar set produces an `IGNITION` transition with `analyze_candidate_day`.

Then iterate bar prefixes. For every prefix call `analyze_candidate_day(prefix, qualification, cfg)` and capture the first transition row where `state == "IGNITION"`. Require no live adapter FIRE before that timestamp and exact equality when it appears.

Qualification must include `population="BOTH"`, `leo_pm_pass=True`, `leo_open_pass=True`, plus the fields required by `analyze_candidate_day`; keep all qualification values fixed while bar prefixes grow.

- [ ] **Step 2: Add normalization assertion**

For a midday ignition timestamp, adapter descriptor variant must normalize to `LEO_BOTH_MIDDAY`; morning observation remains `MORNING_OBSERVATION`; after-hours BOTH remains `LEO_BOTH_AH`. Use the same mapping currently implemented in `scanner/strategies/serclick_leo/strategy.py`.

- [ ] **Step 3: Run RED**

```bash
PYTHONPATH=. pytest -q tests/live/test_serclick_live_parity.py
```

- [ ] **Step 4: Implement adapter by re-running existing SerClick analysis on the current prefix**

Mapping:
- latest `SHORTS_BUILDING` or `ABSORPTION` -> WATCH;
- latest `ARMED` -> ARMED;
- latest `IGNITION` -> FIRE;
- no known transition at latest bar -> no new intent.

Do not copy absorption/expansion/pain logic into `scanner/live`; `analyze_candidate_day` remains authoritative.

Because `event_df` adds next-bar entry data only when a future bar exists, live FIRE timing must come from `transitions`, which already records `IGNITION` at the trigger bar.

- [ ] **Step 5: Run SerClick regressions**

```bash
PYTHONPATH=. pytest -q \
  tests/live/test_serclick_live_parity.py \
  tests/test_no_cost_serclick_end_to_end.py \
  tests/test_pipeline.py \
  tests/test_features.py
```

- [ ] **Step 6: Commit**

```bash
git add scanner/live/adapters/serclick_leo.py scanner/strategies/serclick_leo/strategy.py tests/live/test_serclick_live_parity.py
git commit -m "feat: add SerClick Leo live parity adapter"
```

---

### Task 8: Fake stream, scanner service, end-to-end safety tests, and Phase 1 docs

**Files:**
- Create: `scanner/live/fake_stream.py`
- Create: `scanner/live/service.py`
- Test: `tests/live/test_live_service_end_to_end.py`
- Modify: `README.md`
- Create: `docs/research/unified_live_scanner_phase1.md`

**Interfaces:**
- `FakeMarketStream(events)` iterable yielding deterministic `MarketBar` values.
- `ScannerService(registry, ledger, feature_engine, lifecycle, feed_health)`.
- `process_bar(bar, context) -> list[LiveSignalEvent]`.
- `active_events()`.
- `ranked_snapshot()`.

- [ ] **Step 1: Write RED production long-FIRE end-to-end test**

Use the exact ORB long-breakout fixture from Task 6. Register ORB_LONG_BREAK as production eligible. Monkeypatch `requests.sessions.Session.request` to raise `AssertionError` if any HTTP call occurs. Feed all bars through `ScannerService.process_bar`.

Require:
- exactly one `FIRE LONG` event;
- persisted event count remains one after later non-transition bars;
- `ranked_snapshot()[0]` is the symbol;
- no network access occurs.

- [ ] **Step 2: Add research-only version of same test**

Use identical bars but leaderboard eligibility false. Require exactly `RESEARCH FIRE`, never `FIRE LONG`, and persistence still occurs.

- [ ] **Step 3: Add multi-edge and conflict tests with explicit local fake adapters**

Define minimal test adapters in `test_live_service_end_to_end.py` implementing the protocol and returning fixed StrategyIntent values at one chosen timestamp. Scenario A: ORB + VWAP LONG -> consensus label at least `CONFIRMED` and higher score than single edge. Scenario B: independent LONG + SHORT on same symbol -> `CONFLICT` and rank penalty.

- [ ] **Step 4: Add stale-feed and restart idempotency tests**

Force health STALE before a would-be production FIRE; require DATA_DEGRADED instead. Then close/reopen the ledger and service for the same session, restore latest events, replay the already-seen final bar, and require no duplicate event row and no fabricated new FIRE.

- [ ] **Step 5: Run RED**

```bash
PYTHONPATH=. pytest -q tests/live/test_live_service_end_to_end.py
```

- [ ] **Step 6: Implement fixed orchestration order**

```text
validate + append completed bar
-> update feed health from event timestamp
-> calculate one FeatureSnapshot
-> evaluate every enabled adapter once
-> lifecycle.apply each intent
-> persist every emitted transition
-> signal-bus publish every emitted transition
-> rebuild consensus and ranked snapshot
```

`ScannerService` contains no ORB/VWAP/SerClick thresholds.

- [ ] **Step 7: Implement restore state**

On construction with `restore_session_date`, load latest events from SQLite into lifecycle prior-state memory. Stable IDs plus SQLite primary keys must make replay of an already-seen transition a no-op.

Real reconnect-gap reconciliation and `MISSED_DURING_GAP` are explicitly Phase 2 because they require a real transport.

- [ ] **Step 8: Write Phase 1 documentation**

README section must say: API-free core only, ORB/VWAP/SerClick parity, lifecycle/gating, consensus ranker, SQLite ledger, no real SIP stream yet, no order routing.

`docs/research/unified_live_scanner_phase1.md` records:
- stable ID scheme;
- bar-prefix/no-lookahead rule;
- batch/live parity definition;
- correlation multipliers 1.00/0.35/0.15;
- scoring weights 35/20/15/10/10/5/5;
- RESEARCH FIRE rule;
- stale/recovery block;
- SQLite schema;
- Phase 2 deferrals.

- [ ] **Step 9: Run complete repository verification**

```bash
PYTHONPATH=. pytest -q
python -m compileall -q scanner scripts
git status --short
```

Expected: full green suite, compile success, clean working tree after commit.

- [ ] **Step 10: Check execution boundary**

```bash
git grep -nE "submit_order|place_order|create_order" -- ':!docs/superpowers/*'
git diff main...HEAD -- scanner/live scanner/strategies scanner/core/models.py
```

Confirm no broker order function was introduced and no unrelated strategy threshold changed.

- [ ] **Step 11: Commit**

```bash
git add scanner/live/fake_stream.py scanner/live/service.py tests/live/test_live_service_end_to_end.py README.md docs/research/unified_live_scanner_phase1.md
git commit -m "feat: complete API-free unified scanner phase 1"
```

---

## Phase 1 Definition of Done

1. `tests/live` is fully API-free.
2. ORB live trigger timestamp/variant/direction/stop matches batch truth on locked synthetic fixtures.
3. VWAP live trigger timestamp/variant/direction/stop matches batch truth for long reclaim and short rejection.
4. SerClick live ignition timing matches `analyze_candidate_day` prefix truth.
5. Research-only strategies cannot emit an unlabeled production FIRE.
6. STALE, DISCONNECTED, and RECOVERING block new production FIRE.
7. Duplicate lifecycle transitions neither alert nor persist twice.
8. Consensus controls correlated variants and surfaces LONG/SHORT conflict.
9. Ranking uses the exact 35/20/15/10/10/5/5 composition and is never described as probability of profit.
10. SQLite restart preserves stable signal/event identity and prevents duplicates.
11. Existing full repository tests remain green.
12. No real network market stream and no broker order routing exist yet.

## Next Plan Boundary

Only after this plan is green, write Phase 2 for Alpaca SIP streaming, staged subscriptions, reconnect-gap reconciliation, real feed health, action-board presentation, observability, and prospective paper soak. Broker routing remains out of scope.
