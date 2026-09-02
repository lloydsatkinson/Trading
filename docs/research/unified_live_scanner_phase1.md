# Unified Live Scanner — Phase 1

Phase 1 is the deterministic, API-free core of the unified real-time scanner. It proves that the existing research strategies can be evaluated causally from completed one-minute bar prefixes, production eligibility can be enforced centrally, and every emitted transition can be forward-recorded without introducing broker execution.

## Scope

Implemented in Phase 1:

- bounded point-in-time symbol state;
- shared market feature calculation;
- ORB, VWAP and SerClick/Leo live adapters;
- batch/live trigger parity tests;
- authoritative research/production evidence binding;
- lifecycle and feed-health gating;
- correlation-aware consensus;
- unified 0–100 ranking;
- deterministic fake stream;
- idempotent SQLite forward ledger;
- restart restoration and replay de-duplication;
- API-free end-to-end scanner orchestration.

Not implemented in Phase 1:

- real Alpaca SIP WebSocket transport;
- dynamic staged subscriptions;
- reconnect-gap backfill / `MISSED_DURING_GAP` reconciliation;
- production action-board UI;
- broker order routing of any kind.

## Causal decision clock

The default decision clock is the **completed one-minute bar**. A live adapter receives only the current prefix held by `SymbolState`; no adapter may use a future bar to decide whether the current bar generated a trigger.

For ORB and VWAP, the shared trigger detector emits a `TriggerDecision` on the signal bar. Historical batch research then attaches the next executable same-session bar for the existing conservative entry/slippage model. The live adapter does not require that next bar to surface the trigger.

SerClick/Leo remains authoritative inside `scanner.serclick.features.analyze_candidate_day`. The live adapter replays that function on each completed prefix and consumes its transition table. `IGNITION` therefore occurs on the causal trigger bar even though the historical event output may later attach next-bar execution fields.

## Stable identities

A signal ID is SHA-256 over the canonical pipe-separated fields:

```text
strategy_id | variant_id | SYMBOL | direction | setup_anchor.isoformat() | strategy_version
```

The digest is truncated to 24 hexadecimal characters.

An event ID is SHA-256 over:

```text
signal_id | effective_state | event_timestamp.isoformat()
```

also truncated to 24 hexadecimal characters.

These IDs are used by lifecycle state, the signal bus and SQLite primary keys so replaying an already-known transition cannot create a second forward observation.

## Batch/live parity definition

Phase 1 parity means the live prefix path must match the corresponding batch research truth for:

- strategy variant;
- direction;
- completed trigger timestamp;
- structural stop reference where the strategy defines one.

The batch path still enters on the next executable bar. Live parity does **not** change that historical execution assumption.

Locked parity coverage:

- `ORB_LONG_BREAK` on the existing eight-bar ORB fixture;
- `VWAP_LONG_RECLAIM`;
- `VWAP_SHORT_REJECTION`;
- SerClick/Leo first causal `IGNITION` transition.

Existing ORB pullback, failed-gap and negative-gap regression tests remain green after trigger extraction.

## Production evidence gate

A strategy adapter cannot self-declare itself production-ready. `StrategyRegistry` binds each adapter to the authoritative leaderboard row matched by:

```text
strategy_id + variant_id + direction
```

A missing or ineligible row is research-only. A research strategy can still emit and be forward-measured, but a FIRE is labelled `RESEARCH FIRE`, never an unlabeled production action.

Production FIRE is additionally blocked when feed health is `STALE`, `DISCONNECTED` or `RECOVERING`; the lifecycle emits `DATA_DEGRADED` instead.

## Consensus

Consensus is calculated per symbol and direction. Multiple variants in the same correlation group receive diminishing contribution multipliers:

```text
1st variant: 1.00
2nd variant: 0.35
3rd+ variant: 0.15 each
```

Independent groups each receive a new full-strength contribution.

Confidence labels:

- one active family: `SINGLE_EDGE`;
- two independent active families: `CONFIRMED`;
- three or more independent active families: `MULTI_EDGE`;
- simultaneous opposing active directions: `CONFLICT`.

A LONG/SHORT conflict is surfaced explicitly rather than averaged away.

## Unified ranking

The visible score is a ranking score from 0 to 100, **not a probability of profit**.

Composition:

```text
35% historical evidence
20% setup quality
15% participation / RVOL
10% catalyst quality
10% consensus
 5% execution quality
 5% validated regime / time edge
```

Unknown catalyst or regime inputs are neutral 50 rather than fabricated. Conflict applies a 20-point post-composition penalty. `STALE`, `DISCONNECTED` and `RECOVERING` cap the visible score at 49; lifecycle gating remains the authority that blocks production FIRE.

## Forward ledger

Phase 1 uses SQLite with append-only, idempotent inserts.

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

Serialization is deterministic JSON (`sort_keys=True`, `default=str`); pickle is not used. `INSERT OR IGNORE` plus stable IDs makes duplicate writes a no-op. Restart restoration rebuilds the lifecycle's latest state from the ledger before new bars are processed.

## Scanner service order

For each completed bar, `ScannerService` performs:

```text
validate + append completed bar
→ update feed health
→ calculate one FeatureSnapshot
→ evaluate each enabled adapter once
→ lifecycle.apply each intent
→ persist every emitted transition
→ publish every emitted transition to the signal bus
→ rebuild consensus and ranked snapshot
```

The service contains no ORB, VWAP or SerClick thresholds.

## Verification boundary

The Phase 1 test suite is API-free. End-to-end tests explicitly make HTTP access fail if attempted. They cover:

- one production `FIRE LONG` persisted once;
- research-only `RESEARCH FIRE`;
- independent multi-edge confirmation;
- opposing-direction conflict;
- stale-feed production suppression;
- restart restore + replay with no duplicate FIRE;
- full existing repository regressions and Python compile.

## Phase 2

Phase 2 may begin only after Phase 1 remains green. Its scope is real Alpaca SIP streaming, staged subscriptions, disconnect/reconnect handling, gap reconciliation, feed observability, action-board presentation and prospective paper soak. Broker order routing remains a separate future boundary and is not implied by Phase 2.
