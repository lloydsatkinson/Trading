# Unified Real-Time Scanner Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect the verified Phase 1 scanner core to one real Alpaca SIP market-data stream, recover safely from disconnect gaps, scan the broad US market without evaluating every strategy on every symbol, and publish a live read-only Action Board.

**Architecture:** Keep Phase 1 `ScannerService` as the strategy/lifecycle authority. One Alpaca `v2/sip` WebSocket emits normalized bars, staged quotes, trading-status messages and LULD bands. Wildcard minute bars feed a lightweight O(1) discovery gate; only promoted symbols are REST-primed into full scanner state and quote-subscribed. Recovery seeds missing bars without replaying production FIRE, and a separate atomic JSON snapshot feeds a read-only Streamlit Action Board.

**Tech Stack:** Python 3.12; pandas/NumPy; `requests`; `websocket-client>=1.8,<2`; `streamlit>=1.40,<2`; SQLite; pytest; Alpaca Market Data v2 SIP; existing `scanner.serclick.alpaca_rest.AlpacaRest`.

**Spec:** `docs/superpowers/specs/2026-09-02-unified-realtime-scanner-v1-design.md`

## Global Constraints

- No broker order creation, submission, replacement or cancellation code.
- Exactly one Alpaca SIP WebSocket connection; never one connection per strategy/symbol.
- Endpoint: `wss://stream.data.alpaca.markets/v2/sip` unless explicitly overridden for the Alpaca test stream.
- Credentials come only from `AlpacaCredentials.from_env()` and are never logged.
- Initial subscriptions: `bars:["*"]`, `statuses:["*"]`, `lulds:["*"]`; quotes are staged to promoted symbols.
- Completed one-minute `b` bars remain the strategy clock. `updatedBars` do not retroactively create production signals.
- Broad discovery reuses `MultiStrategyConfig`: absolute gap >= 5%, activity >= $1m, price $1-$30; Leo extension > 20% may also promote.
- Candidate REST priming uses 04:00 ET through strictly before the current live bar; that current live bar is then processed exactly once.
- Disconnect => `RECOVERING`; gap bars are inspected/seeded without live alerts; triggers inside the gap become `MISSED_DURING_GAP` diagnostics.
- Production FIRE stays blocked while feed state is STALE, DISCONNECTED or RECOVERING.
- Actual halt/pause statuses block production FIRE. CTA `2` is halt and `3` resume; UTP `H` is halt, `P` volatility pause, and `Q`/`T` resume. Message text is only a defensive fallback.
- LULD `l` messages provide limit-up/down bands and do not by themselves mark the symbol halted; they remain visible and can reduce execution quality when price is near a band.
- Action Board is read-only and has no order controls.
- Normal CI is API-free through fake socket/REST injection. Real-SIP smoke is manual only.
- Existing Phase 1 and research tests stay green.

## File Map

Create:

```text
scanner/live/alpaca_protocol.py
scanner/live/alpaca_stream.py
scanner/live/discovery.py
scanner/live/bootstrap.py
scanner/live/recovery.py
scanner/live/status_book.py
scanner/live/runtime.py
scanner/live/action_board.py
scanner/live/live_registry.py
scripts/run_live_scanner.py
scripts/run_action_board.py
tests/live/test_alpaca_protocol.py
tests/live/test_alpaca_stream.py
tests/live/test_discovery_bootstrap.py
tests/live/test_recovery.py
tests/live/test_runtime.py
tests/live/test_action_board.py
.github/workflows/live-scanner-smoke.yml
docs/research/unified_live_scanner_phase2.md
```

Modify:

```text
requirements.txt
scanner/live/models.py
scanner/live/service.py
scanner/live/forward_ledger.py
scanner/live/symbol_state.py
README.md
```

---

### Task 1: SIP wire protocol and one-socket transport

**Files:** `requirements.txt`, `scanner/live/models.py`, new `scanner/live/alpaca_protocol.py`, new `scanner/live/alpaca_stream.py`, tests `test_alpaca_protocol.py`, `test_alpaca_stream.py`.

**Produces:**
- frozen `MarketQuote(symbol, timestamp, bid, ask, bid_size, ask_size)`;
- frozen `MarketStatus(symbol, timestamp, halted, code, message, reason_code, reason_message)`;
- frozen `MarketLuld(symbol, timestamp, limit_up, limit_down, indicator)`;
- `decode_alpaca_payload(payload) -> list[MarketBar | MarketQuote | MarketStatus | MarketLuld | dict]`;
- `AlpacaSIPStream.connect()`, `subscribe_initial()`, `set_quote_symbols()`, `recv_events()`, `close()`.

- [ ] **Step 1: Write failing decoder tests.**

```python
def test_decode_stock_stream_payload():
    raw = '[{"T":"b","S":"ABC","o":2,"h":2.4,"l":1.9,"c":2.3,"v":1000,"t":"2026-09-02T14:35:00Z"},' \
          '{"T":"q","S":"ABC","bp":2.29,"ap":2.31,"bs":10,"as":12,"t":"2026-09-02T14:35:05Z"},' \
          '{"T":"s","S":"ABC","sc":"H","sm":"Trading Halt","rc":"T12","rm":"Trading Halted","t":"2026-09-02T14:35:06Z"},' \
          '{"T":"l","S":"ABC","u":2.60,"d":2.10,"i":"B","t":"2026-09-02T14:35:07Z"}]'
    events = decode_alpaca_payload(raw)
    assert events[0].close == 2.3
    assert events[1].ask == 2.31
    assert events[2].halted is True
    assert events[3].limit_up == 2.60
```

Also test CTA `2 -> halted`, CTA `3 -> resumed`, UTP `P -> halted/pause`, and `Q/T -> resumed`.

- [ ] **Step 2: Run decoder tests and confirm missing-module RED.**
- [ ] **Step 3: Implement strict decoding with timezone-aware timestamps, nonnegative market prices/sizes, raw unknown-message diagnostics, and no secret fields.**
- [ ] **Step 4: Write failing socket tests using an injected fake WebSocket.**

```python
def test_one_socket_auth_then_subscribe(fake_factory, creds):
    s = AlpacaSIPStream(creds, ws_factory=fake_factory)
    s.connect(); s.subscribe_initial()
    assert fake_factory.calls == 1
    assert fake_factory.sent[0] == {"action":"auth","key":"k","secret":"s"}
    assert fake_factory.sent[1] == {"action":"subscribe","bars":["*"],"statuses":["*"],"lulds":["*"]}
```

Test auth timeout, 406 connection-limit error, feed-entitlement/auth error, and quote-subscription delta add/remove.

- [ ] **Step 5: Implement `AlpacaSIPStream` with production default `websocket.create_connection`, array-framed control/data parsing, one socket instance and secret-free errors.**
- [ ] **Step 6: Add `websocket-client>=1.8,<2` and `streamlit>=1.40,<2` to requirements; run Task 1 tests, full `pytest -q`, `pip check`, compile; commit.**

---

### Task 2: Broad discovery, prior-close bootstrap, candidate priming and status book

**Files:** new `discovery.py`, `bootstrap.py`, `status_book.py`; modify `symbol_state.py`, `service.py`; test `test_discovery_bootstrap.py`.

**Produces:**
- `DiscoveryDecision(symbol, promoted, reason_codes, prior_close, gap_pct, activity_dollar)`;
- `DiscoveryGate.observe(bar)`;
- `SessionBootstrap.load_prior_closes(session_date)` and `prime_symbol(symbol, session_date, before_ts)`;
- `StatusBook.update_quote/status/luld`, `spread_pct`, `is_halted`, `luld_distance_pct`;
- `ScannerService.seed_bar(bar, context)`.

- [ ] **Step 1: Write failing discovery tests.**

```python
def test_gap_activity_promotes_once():
    gate = DiscoveryGate({"ABC": 2.0})
    assert not gate.observe(bar("ABC", "08:00", 2.08, 100_000)).promoted
    decision = gate.observe(bar("ABC", "08:01", 2.20, 500_000))
    assert decision.promoted
    assert "GAP_ACTIVITY" in decision.reason_codes
    assert gate.observe(bar("ABC", "08:02", 2.22, 10_000)).newly_promoted is False
```

Test locked $1-$30 broad gate and Leo >1.20 extension promotion with meaningful activity.

- [ ] **Step 2: Confirm RED; implement O(1) per-bar discovery using only prior close, latest/high price and cumulative typical-price dollar turnover.**
- [ ] **Step 3: Write failing bootstrap tests using fake `AlpacaRest`: active US equities only, latest daily close strictly before session date, batch size <=200, prime bars sorted and `< before_ts`.**
- [ ] **Step 4: Implement bootstrap by reusing `AlpacaRest.assets/calendar/stock_bars`; no new HTTP client.**
- [ ] **Step 5: Write and implement `StatusBook`; LULD band state is separate from halt status.**
- [ ] **Step 6: Add idempotent `ScannerService.seed_bar`. It may build bar state/features but never call adapters, lifecycle, ledger event insertion or signal bus.**
- [ ] **Step 7: When normal `process_bar` context says `_symbol_halted=True`, a production FIRE intent becomes HALTED; LULD proximity only adjusts execution context/score. Run full suite/compile; commit.**

---

### Task 3: Reconnect gap recovery without retroactive FIRE

**Files:** new `recovery.py`; modify `models.py`, `forward_ledger.py`, `service.py`; test `test_recovery.py`.

**Produces:** `GapDiagnostic`, ledger gap table, `ScannerService.inspect_seed_bar`, `GapReconciler.recover`.

- [ ] **Step 1: Write failing missed-gap test.**

```python
def test_gap_trigger_is_diagnostic_not_live_fire(service, fake_rest, ledger, bus):
    out = GapReconciler(fake_rest, service).recover({"ABC"}, t0, t3, context_for)
    assert any(x.reason == "MISSED_DURING_GAP" for x in out)
    assert bus.published == []
    assert ledger.event_count() == 0
    assert ledger.gap_diagnostic_count() == 1
```

- [ ] **Step 2: Confirm RED; add deterministic diagnostic ID and SQLite `gap_diagnostics` table with `INSERT OR IGNORE`.**
- [ ] **Step 3: Implement `inspect_seed_bar`: append one recovered completed bar, evaluate adapters only to detect same-bar intents, write diagnostics, never apply lifecycle/publish FIRE.**
- [ ] **Step 4: Implement `GapReconciler` with Alpaca 1Min SIP REST bars strictly inside the gap and sorted ascending.**
- [ ] **Step 5: Re-run identical recovery twice and prove one diagnostic/no duplicate signal rows. Feed remains RECOVERING until a fresh stream event is observed. Full suite/compile; commit.**

---

### Task 4: Runtime orchestration and live Action Board

**Files:** new `live_registry.py`, `runtime.py`, `action_board.py`, `scripts/run_live_scanner.py`, `scripts/run_action_board.py`; tests `test_runtime.py`, `test_action_board.py`.

**Produces:** `build_live_registry`, `LiveScannerRuntime.run`, `build_action_rows`, `ActionBoardSnapshotWriter.write`.

- [ ] **Step 1: Write failing runtime integration test.** Feed bars for ABC/XYZ through a fake wildcard stream; only ABC crosses discovery. Assert ABC alone is REST-primed/quote-subscribed, its prime bars precede current live bar, current bar is processed once, XYZ never reaches strategy evaluation.
- [ ] **Step 2: Confirm RED; implement this exact order:**

```text
bootstrap prior closes
connect/authenticate one SIP socket
subscribe wildcard bars/statuses/lulds
bar -> DiscoveryGate
  newly promoted -> REST prime bars < current timestamp -> stage quote subscription
  promoted -> process current bar once with spread/halt/LULD context
quote/status/luld -> StatusBook -> refresh board
socket loss -> begin RECOVERING -> reconnect -> gap recover promoted symbols
first genuinely fresh data event -> mark_recovered -> resume production evaluation
```

- [ ] **Step 3: `build_live_registry` creates ORB/VWAP/SerClick adapters and uses existing `StrategyRegistry` evidence authority; missing/ineligible leaderboard rows stay research-only.**
- [ ] **Step 4: Write failing Action Board shape/order test.** Required row fields: `rank,symbol,last_price,direction,action,score,production_status,primary_strategy,supporting_families,entry_trigger,stop,target_1,target_2,rvol,spread_pct,luld_distance_pct,halted,feed_health,conflict,updated_at`.
- [ ] **Step 5: Implement atomic JSON snapshot (`tmp` + `Path.replace`) and read-only Streamlit viewer; refresh every 2 seconds with no buttons/actions that mutate scanner or trade state.**
- [ ] **Step 6: Implement CLI commands:**

```bash
python scripts/run_live_scanner.py --feed sip --ledger data/live/scanner.db --snapshot data/live/action_board.json
streamlit run scripts/run_action_board.py -- --snapshot data/live/action_board.json
```

Startup checks must validate credentials, evidence/leaderboard input and writable data path without printing secrets.

- [ ] **Step 7: Full suite/compile/pip check; commit.**

---

### Task 5: Manual real-SIP smoke, docs and release gate

**Files:** new `.github/workflows/live-scanner-smoke.yml`, new `docs/research/unified_live_scanner_phase2.md`, modify README/tests.

- [ ] **Step 1: Add `--transport-smoke-seconds N` to `run_live_scanner.py`.** It authenticates/subscribes, counts control/data events, prints only secret-free counters/status and exits without starting strategy alerts.
- [ ] **Step 2: Add manual-only `workflow_dispatch` smoke workflow using existing Alpaca secrets. No `schedule`, `push` or broker-order endpoint.**
- [ ] **Step 3: Document one-connection constraint, SIP entitlement/auth failures, launch commands, board fields, reconnect/recovery, `MISSED_DURING_GAP`, SQLite/JSON files, shutdown/restart and no-order boundary.**
- [ ] **Step 4: Open draft Phase 2 PR and run final API-free verification: `pytest -q`, `python -m compileall -q scanner scripts`, `pip check`, plus PR diff scan for `submit_order|place_order|create_order|cancel_order` outside docs/tests.**
- [ ] **Step 5: Trigger manual 20-second real-SIP smoke only after API-free CI is green. Success = auth success + subscription confirmation + control message and either at least one market-data event or explicit clean `no_data_during_window`. Entitlement/auth failure blocks declaring the real feed ready but does not invalidate API-free implementation.**
- [ ] **Step 6: Do not merge until CI, manual transport smoke, restart/recovery tests and execution-boundary review are green.**
