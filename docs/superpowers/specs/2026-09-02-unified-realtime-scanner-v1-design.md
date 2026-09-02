# Unified Real-Time Scanner V1 Design

Date: 2026-09-02
Repository: `lloydsatkinson/Trading`
Status: Approved in chat for design; implementation not yet started.
Branch: `design/unified-realtime-scanner-v1`

## 1. Objective

Build one real-time scanner for the user's complete trading research programme rather than running independent scanners for each strategy family.

The scanner must:

- consume one shared live US equity market-data stream;
- calculate reusable market features once per symbol/time slice;
- run every enabled strategy against the same point-in-time state;
- represent all setups through one common signal schema;
- move signals through a common lifecycle: `DISCOVER -> WATCH -> ARMED -> FIRE -> MANAGE -> EXIT`;
- rank opportunities across strategies on one 0-100 action board;
- preserve each strategy's independent rules and historical evidence;
- reward multi-strategy agreement without double-counting highly correlated variants;
- record every qualifying live signal into a forward-test ledger whether or not a human trades it;
- clearly separate validated production signals from research-only signals;
- remain alerting/paper-forward infrastructure in V1 and never auto-route live orders.

The target outcome is a single screen that answers, in plain language: **what is interesting now, which strategy sees it, how strong is the evidence, where is the trigger, where is invalidation, and what should happen next?**

## 2. Existing Foundation

The repository already contains a shared multi-strategy research framework for:

- Stocks-in-Play 5-minute ORB;
- High-RVOL VWAP Momentum/Reclaim;
- SerClick / Leo.

It already provides common research concepts including no-lookahead signal construction, conservative next-bar execution, slippage stress, stop/target grids, hold-time analysis, chronological development/validation/test/forward labels and cross-strategy ranking.

Open research branches additionally contain Dan Irish and Merciless-Q strategy-family work. They must not be copied into the scanner independently. The live engine consumes them only through the same strategy adapter contract after their branches are merged or otherwise made available on the scanner integration branch.

Other strategy families already developed or discussed outside the current merged `Trading/main` codebase, including SBE, LongEdge, Trader9to5, BFR-15/Lionturtle backside, ABCD/HOD-break and Ross-style momentum variants, are treated as adapter targets. V1 architecture must support them without redesigning the live engine.

## 3. Non-Goals

V1 does not:

- place, modify or cancel live broker orders;
- bypass short-locate, borrow, SSR, LULD or halt constraints;
- claim an unvalidated strategy has a proven edge;
- merge strategy logic into one monolithic score function;
- use forward results to retune a locked production rule automatically;
- require every strategy to use identical candidate filters, timing windows, stops or targets;
- infer missing fundamentals/float/catalyst data as if known;
- silently fall back from SIP-quality data to a lower-quality feed without surfacing the degraded state.

## 4. Architectural Choice

Use a **shared market engine plus strategy plug-ins**.

Rejected alternatives:

1. **Independent scanners combined at the UI.** Fast initially but duplicates data work, creates inconsistent timestamps/features and makes ranking/forward testing unreliable.
2. **One giant scanner function.** Operationally simple at first but couples every strategy, makes regression testing difficult and turns each new strategy into a high-risk change.

Selected approach:

```text
Live Market Feed
      |
      v
Market Event Normalizer
      |
      v
Shared Symbol State + Feature Engine
      |
      +----------------+----------------+----------------+
      |                |                |                |
      v                v                v                v
   ORB Adapter      VWAP Adapter     Leo Adapter      ...Adapters
      |                |                |                |
      +----------------+----------------+----------------+
                       |
                       v
                  Signal Bus
                       |
             Lifecycle / Dedup Engine
                       |
                       v
             Evidence + Consensus Ranker
                       |
              +--------+--------+
              |                 |
              v                 v
        Live Action Board   Forward Ledger
```

Each strategy remains independently understandable and testable. The shared engine owns data, state, lifecycle, ranking metadata and persistence, not the strategy's trading thesis.

## 5. Package Design

Target structure:

```text
Trading/
├── scanner/
│   ├── live/
│   │   ├── models.py
│   │   ├── clock.py
│   │   ├── market_stream.py
│   │   ├── normalizer.py
│   │   ├── symbol_state.py
│   │   ├── feature_engine.py
│   │   ├── strategy_registry.py
│   │   ├── signal_bus.py
│   │   ├── lifecycle.py
│   │   ├── consensus.py
│   │   ├── ranker.py
│   │   ├── forward_ledger.py
│   │   └── service.py
│   │
│   ├── strategies/
│   │   └── <existing and future strategy families>/
│   │
│   └── portfolio/
│       └── strategy_ranker.py
│
├── scripts/
│   ├── run_live_scanner.py
│   └── run_strategy_research.py
│
├── tests/
│   ├── live/
│   └── strategies/
│
└── data/
    └── live/
```

Existing research modules are reused rather than moved gratuitously. Where research strategy functions are batch-oriented, a thin live adapter converts point-in-time state into the existing strategy input or exposes a small pure decision function shared by batch and live modes.

## 6. Market Data and Time Model

### 6.1 Primary feed

Primary US live feed: **Alpaca SIP**, reusing the repository's existing Alpaca data relationship and avoiding a separate definition of market truth between research and live monitoring.

Polygon may be used later for cross-checking, gap filling or feed comparison, but not as an invisible mixed source inside one signal.

### 6.2 Session coverage

Default scanner operating window: `04:00-20:00 America/New_York` on valid US trading days.

The service must understand:

- premarket;
- regular session;
- after-hours;
- weekends/holidays/early closes;
- daylight-saving transitions through timezone-aware timestamps.

A strategy may opt into only the windows appropriate to its research. For example, an ORB variant may be regular-session-only while SerClick research can separately observe later-day/after-hours regimes.

### 6.3 Event inputs

The normalizer must support, where the provider supplies them:

- trades;
- quotes;
- minute bars;
- trading status / halt-related state;
- asset metadata snapshots.

The first implementation may drive strategy decisions on completed one-minute bars while quotes/trades maintain current price, spread and execution-quality state. Strategies that require sub-minute triggers are only enabled after an explicit tested sub-minute contract exists.

### 6.4 Feed health

Every signal carries feed-health metadata.

Feed states:

- `LIVE`;
- `DELAYED`;
- `STALE`;
- `DISCONNECTED`;
- `RECOVERING`.

No new production `FIRE` may be emitted from `STALE`, `DISCONNECTED` or ambiguous replayed state. Existing signals remain visible with a degraded-data warning.

## 7. Shared Symbol State

For every active symbol the engine maintains only information known up to the current timestamp.

Core state includes, where known:

- symbol and asset type;
- prior close;
- current/last price;
- bid, ask and quoted spread;
- premarket high/low/volume/dollar turnover;
- regular-session open/high/low/volume/dollar turnover;
- HOD/LOD as known now;
- session VWAP;
- one-minute rolling bars;
- five-minute derived context;
- RVOL using same-time-of-day historical baselines when available;
- volume acceleration;
- ATR / realised volatility;
- gap %;
- retained gain from impulse;
- range contraction / expansion features;
- market cap, float and price buckets when date-valid metadata is available;
- SSR status when reliably available;
- halt/LULD-related state when available;
- catalyst/news classification only when the timestamp proves the information was available by the decision time.

Unknown values remain explicit `UNKNOWN`; they are not silently imputed.

## 8. Strategy Adapter Contract

Every live-enabled strategy implements the same conceptual interface.

Required metadata:

- `strategy_id`;
- `strategy_family`;
- `variant_id`;
- `direction` capability (`LONG`, `SHORT`, `BOTH`);
- eligible session windows;
- evidence status;
- production eligibility;
- correlation group;
- required features;
- stale-data tolerance;
- strategy version / rule hash.

Required behavior:

1. **discover(state)** — cheap candidate screening; may return nothing or a low-cost candidate record.
2. **evaluate(state, prior_signal_state)** — returns the next strategy-specific lifecycle intent and structured evidence.
3. **risk_plan(state, signal)** — returns entry trigger/reference, invalidation/stop reference, targets or management rules when defined by the validated strategy.
4. **explain(state, signal)** — returns machine-readable reason codes plus concise human explanation.

Adapters must be deterministic for a given timestamped input state.

A strategy adapter may not directly mutate another strategy's state, rank, dashboard row or ledger entry.

## 9. Strategy Registry and Evidence Status

The registry is the single source of truth for which strategies are enabled and how they are allowed to surface.

Evidence states:

- `RESEARCH` — hypothesis or active research; can produce `DISCOVER/WATCH/ARMED`, but not production `FIRE`;
- `VALIDATION` — rules being selected/validated; live observations recorded, no production `FIRE`;
- `LOCKED_TEST` — locked historical test in progress; no production `FIRE` until gate is passed;
- `FORWARD_ONLY` — locked rules gathering prospective evidence; may remain non-production until gate is passed;
- `PRODUCTION_ELIGIBLE` — strategy has passed the repository's production evidence gate;
- `DISABLED` — not evaluated live.

A research signal can still display an internal trigger-like event for measurement, but the user-facing action must say `RESEARCH FIRE` or equivalent and must never be confused with a production action.

The existing production expectancy hurdle and any later production-gate logic remain authoritative; the live scanner consumes the gate result rather than inventing a second evidence standard.

## 10. Initial Strategy Mapping

### 10.1 Already merged foundation

- Stocks-in-Play ORB: long and short variants.
- High-RVOL VWAP Momentum/Reclaim: long and short variants.
- SerClick / Leo: compatibility adapter preserving locked Leo gates and existing time-regime rules.

### 10.2 Branch/research families

- Dan Irish family: registry entry remains research-gated until its branch/research evidence qualifies.
- Merciless-Q family: registry entry remains research-gated until its branch/research evidence qualifies.

### 10.3 Planned adapters

The architecture must accept without redesign:

- SBE;
- LongEdge candidate discovery;
- Trader9to5 signals;
- BFR-15 / Lionturtle backside;
- ABCD continuation;
- HOD-break variants;
- Ross-style momentum variants;
- any future long/short strategy with deterministic point-in-time rules.

LongEdge may act primarily as a candidate-discovery family rather than an entry strategy. Such families contribute candidate/evidence metadata but do not receive the same consensus weight as an independent validated entry trigger unless validation demonstrates they add independent information.

## 11. Common Signal Schema

Every emitted signal event contains at minimum:

- `signal_id`;
- `strategy_id`;
- `strategy_family`;
- `variant_id`;
- `strategy_version`;
- `symbol`;
- `direction`;
- `event_timestamp`;
- `market_session`;
- `lifecycle_state`;
- `production_status`;
- `reference_price`;
- `entry_trigger` or entry zone when defined;
- `stop_reference` / invalidation;
- target references or management policy when defined;
- `setup_score`;
- `evidence_score`;
- `execution_score`;
- reason codes;
- human explanation;
- feed-health state;
- market-cap/float/liquidity/time buckets;
- catalyst class when known;
- correlation group;
- source event/bar timestamp.

The signal event is immutable. Lifecycle changes append a new event referencing the same logical signal identity.

## 12. Lifecycle State Machine

Canonical user-facing lifecycle:

1. `DISCOVER` — symbol entered a strategy's cheap candidate universe.
2. `WATCH` — meaningful setup forming but trigger prerequisites are incomplete.
3. `ARMED` — setup prerequisites are satisfied and a concrete trigger/invalidation can be stated.
4. `FIRE` — validated trigger has occurred on completed/allowed data and production gating permits the action label.
5. `MANAGE` — signal is active for forward measurement; targets/stops/trailing conditions are being observed.
6. `EXIT` — stop, target, time exit, invalidation or strategy-specific exit occurred.

Terminal/exception states:

- `INVALIDATED`;
- `EXPIRED`;
- `DATA_DEGRADED`;
- `HALTED`.

State transitions must be monotonic for one logical setup except that a new setup on the same symbol may create a new `signal_id` after the earlier one terminates.

No repeated alert spam is allowed. A lifecycle transition alerts once; ordinary price updates do not create duplicate alerts.

## 13. Deduplication and Correlation Control

Multiple strategy agreement is useful, but correlated variants must not be counted as independent votes.

Examples:

- direct ORB and ORB pullback are in one ORB correlation family;
- multiple parameter variants of VWAP reclaim are one VWAP family;
- HOD break and a strategy whose trigger is mechanically the same HOD break may be partially correlated;
- LongEdge candidate score is upstream discovery evidence, not automatically a second independent entry edge.

The engine groups signals by `correlation_group` and applies diminishing consensus contribution inside each group.

Consensus rewards breadth across genuinely different families, for example:

- impulse/consolidation breakout;
- VWAP demand recovery;
- absorption/trap/squeeze;
- backside/exhaustion short;
- catalyst/liquidity quality.

The raw individual strategy signals always remain visible so the consensus layer cannot hide disagreement.

## 14. Scoring Model

The live action board reports a normalized 0-100 `unified_score`.

The score is not a predicted probability of profit. It is a ranking score built only from evidence available now.

Initial composition:

- 35% historical/forward evidence quality for the locked strategy rule;
- 20% current setup quality produced by that strategy;
- 15% participation/liquidity quality including RVOL/dollar turnover;
- 10% timestamp-valid catalyst quality when known;
- 10% independent multi-strategy consensus;
- 5% execution quality including spread/slippage/halt risk;
- 5% validated time-of-day/regime fit.

Research-only strategies have their evidence component capped and cannot outrank a materially stronger production signal merely through unvalidated setup scoring.

Hard penalties or blocks apply to:

- stale/disconnected feed;
- unacceptable spread or liquidity for the strategy's validated regime;
- missing required feature;
- halt/data ambiguity;
- trigger materially exceeded before processing, causing chase risk;
- strategy-specific invalidation;
- live conditions outside the rule's validated universe;
- short-side availability constraints where a production action would otherwise imply executability.

## 15. Consensus Signal

For each symbol and direction, the consensus engine aggregates simultaneously active independent strategy-family evidence.

Outputs:

- number of active families;
- number of production-eligible families;
- weighted consensus contribution;
- strongest supporting families;
- contradicting opposite-direction families;
- consensus confidence label such as `SINGLE_EDGE`, `CONFIRMED`, `MULTI_EDGE`.

Opposite-direction evidence is never averaged away silently. A symbol with strong long and short signals should show `CONFLICT` and receive an appropriate rank penalty or manual-review requirement.

## 16. Action Board

Primary table columns:

- rank;
- symbol;
- last price;
- direction;
- action;
- unified score;
- production/research badge;
- primary strategy;
- supporting strategies;
- trigger/entry zone;
- stop/invalidation;
- T1;
- T2 or management rule;
- lifecycle state;
- RVOL;
- spread;
- time since latest transition;
- feed health.

Primary action labels:

- `FIRE LONG`;
- `FIRE SHORT`;
- `ARMED LONG`;
- `ARMED SHORT`;
- `WATCH`;
- `RESEARCH FIRE`;
- `INVALIDATED`;
- `TAKE PROFIT` when strategy management explicitly supports it;
- `EXIT`.

Default sort priority:

1. production `FIRE`;
2. production `ARMED`;
3. highest-scoring production `WATCH`;
4. research signals;
5. invalidated/expired history.

The dashboard is a view over engine state, not the place where trading logic lives.

## 17. Forward-Test Ledger

Every `FIRE`-equivalent event, including research-only trigger events, is persisted automatically.

The ledger records:

- signal identity and exact strategy version;
- event timestamps;
- point-in-time features;
- entry/reference price;
- planned stop/targets/hold policy;
- production status at signal time;
- feed health;
- subsequent stop/target/time outcomes under the same conservative replay conventions used by research;
- MFE/MAE;
- best excursion and time-to-peak;
- slippage scenarios where enough quote/bar data is available;
- whether the user manually marked the idea as traded, skipped or not seen.

Forward data is append-only for evidence purposes. Corrections to data quality are versioned rather than overwriting historical signal facts silently.

The ledger must support daily and rolling summaries by:

- strategy/variant;
- long/short;
- production/research status;
- market-cap/float/price bucket;
- time of day;
- catalyst class;
- consensus tier;
- score decile.

## 18. Persistence

V1 should use a simple durable local store suitable for the existing Python repository, with an abstraction that permits later migration.

Recommended first store: SQLite for:

- signal events;
- lifecycle transitions;
- forward outcomes;
- scanner health events;
- optional user annotations.

Large market bars remain cached/artifact data rather than being duplicated excessively into the event database.

Writes must be idempotent by stable event keys so reconnect/replay cannot duplicate signal events.

## 19. Recovery and Restart Behavior

On restart:

1. load trading calendar/session context;
2. load latest persisted signal/lifecycle state for the current session;
3. obtain enough recent market bars/state to reconstruct features without lookahead;
4. reconnect to the live feed;
5. mark the system `RECOVERING`;
6. reconcile timestamps and detect any gap;
7. only return to `LIVE` when the required state is coherent.

A reconnect must not retroactively emit a production `FIRE` as if it was seen live if the trigger happened during an unobserved gap. It may record a `MISSED_DURING_GAP` research/diagnostic event for later analysis.

## 20. Alerts

Alert transport is downstream from the signal bus.

V1 may start with console/dashboard notifications. Email, SMS/WhatsApp or broker integrations are separate adapters and must consume lifecycle transitions rather than duplicate strategy logic.

Alert policy:

- one alert on transition to `ARMED` when enabled;
- one alert on transition to `FIRE`;
- one alert on material management/exit state when configured;
- no repeated alert merely because a symbol remains in the same state;
- research-only alerts are visually and textually distinct from production alerts.

## 21. Safety and Execution Boundary

`Trading` remains a research, scanner and decision-support repository in V1.

No live-order routing is introduced.

Any future broker execution project must have a separate explicit design covering:

- account/broker integration;
- authentication/secrets;
- position sizing;
- max daily loss;
- max symbol exposure;
- duplicate-order prevention;
- locate/borrow constraints;
- halt and SSR behavior;
- kill switch;
- reconciliation;
- paper/live separation.

The scanner's `FIRE` is therefore an **actionable signal label**, not an automatic order instruction.

## 22. Testing Strategy

Implementation follows TDD.

### 22.1 Unit tests

Cover:

- timezone/session clock behavior;
- market event normalization;
- VWAP/RVOL/volume acceleration and point-in-time features;
- feed-health transitions;
- strategy registry/evidence gating;
- lifecycle transition legality;
- deduplication;
- correlation-group diminishing consensus;
- opposite-direction conflict handling;
- ranking and penalties;
- forward-ledger idempotency;
- restart/recovery gap behavior.

### 22.2 Strategy parity tests

For merged strategies, feed identical historical point-in-time bars into batch research and live adapters and require equivalent trigger decisions for the locked rule.

This is the critical proof that "live" is not a subtly different strategy from the one that was backtested.

### 22.3 Synthetic end-to-end tests

Run an API-free deterministic fake stream through:

`events -> state -> features -> strategies -> lifecycle -> ranker -> ledger`

Require known scenarios for:

- long FIRE;
- short FIRE;
- multiple agreeing strategies;
- conflicting strategies;
- research-only trigger blocked from production FIRE;
- feed disconnect/recovery;
- halt/stale-data block;
- restart without duplicate signals.

### 22.4 Live paper soak

Before the scanner is treated as production decision support, operate prospectively with order routing absent and compare:

- emitted signals against expected chart behavior;
- live features against historical recomputation;
- signal timestamps against provider timestamps;
- forward outcomes against conservative replay;
- missed/duplicate alert rate;
- feed stability across premarket, regular session and after-hours.

## 23. Observability

The live service must expose/log at minimum:

- connection/feed state;
- provider and feed name;
- last event timestamp and event lag;
- number of symbols tracked;
- number of active signals by lifecycle state;
- number of production vs research signals;
- evaluation latency;
- dropped/malformed event counts;
- recovery gaps;
- database write failures.

A scanner that cannot prove its data is live must not display ordinary production FIRE states without a warning/block.

## 24. Performance Principles

The engine must not subscribe blindly to every calculation for every US symbol on every tick.

Use staged work:

1. broad provider universe / cheap discovery;
2. active-candidate set;
3. full feature calculation only for candidates or symbols required by an enabled strategy;
4. strategy evaluation on completed decision intervals/events.

Shared features are memoized per symbol/timestamp so ten strategies do not independently recompute VWAP, HOD, RVOL or the same rolling statistics.

Correctness and timestamp integrity take priority over sub-second cosmetic updates.

## 25. Configuration

Configuration separates:

- provider credentials via environment/secrets only;
- live provider/feed;
- enabled strategies;
- strategy evidence/production status loaded from authoritative research outputs/config;
- alert preferences;
- persistence path;
- dashboard refresh preferences;
- logging level.

No API key is committed to source, generated artifacts or tests.

Production evidence thresholds are not editable ad hoc from the dashboard.

## 26. Rollout Sequence

Implementation is intentionally staged.

### Phase 1 — Engine skeleton and parity

- live event/data models;
- fake stream;
- symbol state/feature engine;
- registry;
- lifecycle;
- SQLite ledger;
- API-free end-to-end test;
- ORB/VWAP/SerClick live adapters with batch/live parity tests.

### Phase 2 — Real SIP paper scanner

- Alpaca SIP streaming adapter;
- feed health/reconnect;
- action-board output;
- forward ledger running prospectively;
- no broker routing.

### Phase 3 — Research-family integration

As the relevant research branches become available and evidence permits:

- Dan Irish;
- Merciless-Q;
- SBE;
- LongEdge;
- Trader9to5;
- BFR-15;
- remaining validated strategy families.

Each joins through the same registry/adapter contract and is research-gated until eligible.

### Phase 4 — Alert adapters and richer UI

- configurable alert transports;
- historical/live signal drill-down;
- strategy agreement/explanation panel;
- rolling forward-performance view.

Broker execution remains a separate future project.

## 27. Acceptance Criteria

Unified Real-Time Scanner V1 is complete when all of the following are true:

1. One scanner process can evaluate all live-enabled merged strategy families from one shared market state.
2. ORB, VWAP and SerClick locked decisions pass batch/live parity tests.
3. A fake deterministic stream passes full end-to-end tests without network access.
4. Research-only strategies cannot emit an unlabeled production `FIRE`.
5. Production gating is derived from authoritative strategy evidence rather than dashboard configuration.
6. Consensus rewards independent strategies and controls correlated double-counting.
7. Opposing strong signals are surfaced as conflict rather than hidden by averaging.
8. Feed stale/disconnect states prevent new production FIRE decisions.
9. Restart/recovery does not duplicate or fabricate live signals.
10. Every FIRE-equivalent signal is persisted to the forward ledger with exact strategy version and point-in-time context.
11. A live/paper Alpaca SIP session can run through premarket/regular/after-hours supported windows with observable feed health.
12. The action board presents symbol, action, score, strategy evidence, trigger, stop/invalidation, targets/management, lifecycle and production/research status clearly.
13. No live broker order is created anywhere in V1.
14. Existing research tests and current strategy behavior remain green.

## 28. Design Decisions Locked by This Spec

- One shared live engine, not separate scanners.
- Strategy plug-ins/adapters, not a monolith.
- Alpaca SIP is the primary V1 live US feed.
- Completed one-minute decisions are the default initial execution clock unless a strategy has a separately tested sub-minute contract.
- `DISCOVER/WATCH/ARMED/FIRE/MANAGE/EXIT` is the canonical lifecycle.
- Production and research signals share infrastructure but never share an ambiguous user-facing action label.
- Multi-strategy consensus is correlation-aware.
- Every qualifying live trigger is forward-tested automatically.
- SQLite is the initial durable event/forward store behind an abstraction.
- No live auto-order routing is part of V1.

This design intentionally makes future strategy additions incremental: adding a new strategy should require a strategy adapter, tests, registry metadata and evidence status, not changes to the core scanner architecture.
