# Unified Real-Time Scanner Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect the verified Phase 1 scanner core to one real Alpaca SIP market-data stream, recover safely from disconnect gaps, scan the broad US market without evaluating every strategy on every symbol, and publish a live read-only Action Board.

**Architecture:** Keep Phase 1's `ScannerService` as the strategy/lifecycle authority. A new transport layer owns one Alpaca `v2/sip` WebSocket connection and emits normalized bars/quotes/status events. Wildcard one-minute bars feed a lightweight discovery gate; only qualifying symbols are REST-primed into full scanner state and quote-subscribed. Recovery backfills missing bars without retroactively emitting production FIRE, recording `MISSED_DURING_GAP` diagnostics instead. A separate JSON snapshot writer and Streamlit reader present the Action Board without sharing mutable scanner state.

**Tech Stack:** Python 3.12; pandas/NumPy; `requests`; `websocket-client>=1.8,<2`; `streamlit>=1.40,<2`; SQLite; pytest; Alpaca Market Data v2 SIP WebSocket and existing `scanner.serclick.alpaca_rest.AlpacaRest`.

**Spec:** `docs/superpowers/specs/2026-09-02-unified-realtime-scanner-v1-design.md`

## Global Constraints

- Phase 2 remains decision-support/paper-forward-test only; no broker order creation/submission/cancellation code.
- Use exactly one Alpaca market-data WebSocket connection for SIP; do not create one connection per strategy or symbol.
- Default endpoint is `wss://stream.data.alpaca.markets/v2/sip`; credentials come only from existing environment variables handled by `AlpacaCredentials.from_env()`.
- Initial stream subscription is wildcard one-minute bars plus wildcard statuses/LULD where supported. Quotes are staged to active candidates only.
- Completed one-minute bars remain the strategy decision clock.
- Broad discovery reuses `MultiStrategyConfig` values: absolute gap >= 5%, activity >= $1m, price $1-$30; Leo extension > 20% may also promote a symbol.
- A symbol promoted after the session begins is primed with REST minute bars from 04:00 ET through strictly before the current live bar, then the current live bar is processed exactly once.
- On disconnect, feed state becomes `RECOVERING`; missing bars are backfilled and seeded without production alerts. Any causal trigger found inside the gap is stored as `MISSED_DURING_GAP`, not replayed as live FIRE.
- New production FIRE remains blocked while feed state is STALE, DISCONNECTED, or RECOVERING.
- Halt/LULD state blocks new production FIRE for the affected symbol and is visible on the Action Board.
- Action Board is read-only. It may display FIRE, ARMED, WATCH, RESEARCH FIRE, CONFLICT, HALTED, DATA DEGRADED and exit/management states, but never sends an order.
- All network tests in normal CI use injected fake sockets/fake REST clients. A credentialed real-SIP smoke is manual-only.
- Existing Phase 1 tests and historical research APIs must remain green.

## File Map

Create:

```text
scanner/live/
├── alpaca_protocol.py       # decode Alpaca websocket payloads
├── alpaca_stream.py         # one authenticated socket + subscriptions
├── discovery.py             # low-cost all-market candidate promotion
├── bootstrap.py             # prior-close universe bootstrap + candidate REST priming
├── recovery.py              # reconnect gap backfill + missed-trigger diagnostics
├── status_book.py           # quote/halt/LULD point-in-time state
├── runtime.py               # transport -> discovery -> service orchestration
├── action_board.py          # immutable dashboard snapshot + atomic JSON writer
└── live_registry.py         # build the Phase 1 registry/adapters from latest evidence

scripts/
├── run_live_scanner.py
└── run_action_board.py

tests/live/
├── test_alpaca_protocol.py
├── test_alpaca_stream.py
├── test_discovery_bootstrap.py
├── test_recovery.py
├── test_runtime.py
└── test_action_board.py

.github/workflows/
└── live-scanner-smoke.yml   # manual only; no scheduled socket consumption
```

Modify:

```text
requirements.txt
scanner/live/models.py
scanner/live/service.py
scanner/live/forward_ledger.py
scanner/live/symbol_state.py
README.md
docs/research/unified_live_scanner_phase2.md
```

---

### Task 1: Alpaca SIP protocol and single-socket transport

**Files:**
- Modify: `requirements.txt`
- Modify: `scanner/live/models.py`
- Create: `scanner/live/alpaca_protocol.py`
- Create: `scanner/live/alpaca_stream.py`
- Test: `tests/live/test_alpaca_protocol.py`
- Test: `tests/live/test_alpaca_stream.py`

**Interfaces:**
- Add frozen `MarketQuote(symbol, timestamp, bid, ask, bid_size, ask_size)` and `MarketStatus(symbol, timestamp, halted, code, message)`.
- `decode_alpaca_payload(payload: str) -> list[MarketBar | MarketQuote | MarketStatus | dict]`.
- `AlpacaSIPStream(creds, feed="sip", ws_factory=None, timeout_seconds=10.0)`.
- `connect()`, `subscribe_initial()`, `set_quote_symbols(symbols: set[str])`, `recv_events()`, `close()`.

- [ ] **Step 1: Write RED protocol tests**

```python
def test_decode_bar_quote_and_halt():
    payload = '[{"T":"b","S":"ABC","o":2.0,"h":2.4,"l":1.9,"c":2.3,"v":1000,"t":"2026-09-02T14:35:00Z"},' \
              '{"T":"q","S":"ABC","bp":2.29,"ap":2.31,"bs":10,"as":12,"t":"2026-09-02T14:35:05Z"},' \
              '{"T":"s","S":"ABC","sc":"H","sm":"Trading Halt","t":"2026-09-02T14:35:06Z"}]'
    events = decode_alpaca_payload(payload)
    assert events[0].symbol == "ABC"
    assert events[1].ask == 2.31
    assert events[2].halted is True
```

- [ ] **Step 2: Run `pytest tests/live/test_alpaca_protocol.py -q` and confirm missing-module RED.**

- [ ] **Step 3: Implement strict payload decoding.** Reject malformed timestamps/negative prices, ignore unknown data event types by returning a diagnostic dict, and map Alpaca bar timestamps to timezone-aware UTC datetimes. Status codes `H`, `2`, `3`, `10` or status text containing `halt` are treated as halted; resume-style codes/text clear the halt.

- [ ] **Step 4: Write RED socket tests with a fake WebSocket.**

```python
def test_stream_authenticates_and_uses_one_socket(fake_ws_factory, creds):
    stream = AlpacaSIPStream(creds, ws_factory=fake_ws_factory)
    stream.connect()
    stream.subscribe_initial()
    assert fake_ws_factory.calls == 1
    assert {"action":"auth","key":"k","secret":"s"} in fake_ws_factory.socket.sent_json
    assert {"action":"subscribe","bars":["*"],"statuses":["*"],"lulds":["*"]} in fake_ws_factory.socket.sent_json
```

Also assert error code 406 becomes `AlpacaStreamError("connection limit exceeded")`, auth must complete before subscribe, and `set_quote_symbols({"ABC"})` sends only the delta from the current quote subscription.

- [ ] **Step 5: Implement `AlpacaSIPStream` with injected `ws_factory`.** Production default uses `websocket.create_connection`; never log key/secret. Parse Alpaca's array-framed success/error/subscription messages and data payloads.

- [ ] **Step 6: Run Task 1 tests then full `pytest -q` and `python -m compileall -q scanner scripts`.**

- [ ] **Step 7: Commit Task 1.**

---

### Task 2: Broad discovery, prior-close bootstrap, candidate priming, quote/halt state

**Files:**
- Create: `scanner/live/discovery.py`
- Create: `scanner/live/bootstrap.py`
- Create: `scanner/live/status_book.py`
- Modify: `scanner/live/symbol_state.py`
- Modify: `scanner/live/service.py`
- Test: `tests/live/test_discovery_bootstrap.py`

**Interfaces:**
- `DiscoveryGate(prior_close_by_symbol, cfg=MultiStrategyConfig())` with `observe(bar) -> DiscoveryDecision`.
- `DiscoveryDecision(symbol, promoted, reason_codes, prior_close, gap_pct, activity_dollar)`.
- `SessionBootstrap(rest, feed="sip")` with `load_prior_closes(session_date) -> dict[str, float]` and `prime_symbol(symbol, session_date, before_ts) -> list[MarketBar]`.
- `StatusBook.update_quote()`, `update_status()`, `spread_pct(symbol)`, `is_halted(symbol)`.
- `ScannerService.seed_bar(bar, context)` appends historical state without adapter/lifecycle evaluation.

- [ ] **Step 1: Write RED discovery tests.**

```python
def test_discovery_promotes_on_locked_broad_gate():
    gate = DiscoveryGate({"ABC": 2.00})
    d1 = gate.observe(bar("ABC", "08:00", close=2.08, volume=100_000))
    d2 = gate.observe(bar("ABC", "08:01", close=2.20, volume=500_000))
    assert d1.promoted is False
    assert d2.promoted is True
    assert "GAP_ACTIVITY" in d2.reason_codes
```

Test price below $1/above $30 does not promote through the broad gap rule, while an extension above 1.20 can promote via `LEO_EXTENSION` once there is meaningful traded value.

- [ ] **Step 2: Confirm RED.**

- [ ] **Step 3: Implement O(1)-per-bar `DiscoveryGate`.** Track only session date, last/high price and cumulative approximate dollar turnover `(high+low+close)/3 * volume`; do not allocate pandas frames or full minute history for non-promoted symbols.

- [ ] **Step 4: Write bootstrap/prime RED tests using a fake `AlpacaRest`.** Assert active US-equity symbols are loaded, latest valid daily close strictly before `session_date` becomes prior close, and `prime_symbol(..., before_ts)` returns only bars with `timestamp < before_ts` sorted ascending.

- [ ] **Step 5: Implement `SessionBootstrap` by reusing `AlpacaRest.assets`, `.calendar`, and `.stock_bars`; batch symbols at 200 and never request future bars.**

- [ ] **Step 6: Add `StatusBook` and `ScannerService.seed_bar`.** `seed_bar` must be idempotent for already-seen timestamp and must not publish/persist lifecycle events. `process_bar` adds `spread_pct`/halt context from caller-supplied context; when `_symbol_halted=True`, production FIRE is converted to HALTED rather than emitted as FIRE.

- [ ] **Step 7: Run Task 2 tests + full suite/compile; commit.**

---

### Task 3: Disconnect recovery and `MISSED_DURING_GAP`

**Files:**
- Create: `scanner/live/recovery.py`
- Modify: `scanner/live/forward_ledger.py`
- Modify: `scanner/live/service.py`
- Test: `tests/live/test_recovery.py`

**Interfaces:**
- Add frozen `GapDiagnostic(symbol, strategy_id, variant_id, direction, trigger_timestamp, reference_price, reason="MISSED_DURING_GAP")`.
- `ForwardLedger.append_gap_diagnostic(diagnostic)` / `gap_diagnostics(session_date)`.
- `ScannerService.inspect_seed_bar(bar, context) -> list[GapDiagnostic]`: append the bar, evaluate adapters on that completed bar, but never call lifecycle, signal bus, or signal-event insert.
- `GapReconciler(rest, service, feed="sip")` with `recover(symbols, start_exclusive, end_exclusive, context_factory) -> list[GapDiagnostic]`.

- [ ] **Step 1: Write RED test proving a trigger inside downtime is recorded but never published as FIRE.**

```python
def test_gap_trigger_becomes_diagnostic_not_live_event(service, fake_rest, bus, ledger):
    diagnostics = GapReconciler(fake_rest, service).recover(
        {"ABC"}, start_exclusive=t0, end_exclusive=t3, context_factory=context_for,
    )
    assert any(d.reason == "MISSED_DURING_GAP" for d in diagnostics)
    assert bus.published == []
    assert ledger.event_count() == 0
    assert ledger.gap_diagnostic_count() == 1
```

- [ ] **Step 2: Confirm RED.**

- [ ] **Step 3: Add `gap_diagnostics` SQLite table keyed by deterministic diagnostic ID.** Duplicate recovery passes are no-ops.

- [ ] **Step 4: Implement `inspect_seed_bar` and `GapReconciler`.** Fetch only `(start_exclusive, end_exclusive)` 1Min SIP bars, sort them, inspect/seed each once, and leave the service feed monitor in RECOVERING until a genuinely fresh stream event is observed.

- [ ] **Step 5: Test reconnect with the same gap twice, asserting one diagnostic and no duplicate signal/event rows.**

- [ ] **Step 6: Full suite/compile; commit.**

---

### Task 4: Real runtime, staged quote subscriptions, Action Board snapshot and UI

**Files:**
- Create: `scanner/live/live_registry.py`
- Create: `scanner/live/runtime.py`
- Create: `scanner/live/action_board.py`
- Create: `scripts/run_live_scanner.py`
- Create: `scripts/run_action_board.py`
- Test: `tests/live/test_runtime.py`
- Test: `tests/live/test_action_board.py`

**Interfaces:**
- `build_live_registry(leaderboard_path) -> StrategyRegistry` creates only adapters present in Phase 1 and binds production eligibility through the existing registry authority.
- `LiveScannerRuntime(stream, service, bootstrap, discovery, status_book, reconciler, snapshot_writer)` with `run(max_events=None)`.
- `ActionBoardSnapshotWriter(path).write(service, status_book, generated_at)` writes atomic JSON via temp-file + `Path.replace()`.
- `build_action_rows(...) -> list[dict]` with stable display fields.

- [ ] **Step 1: Write RED runtime integration test using fake stream/REST.** Feed all-market bars where only ABC crosses discovery. Assert only ABC is REST-primed, ABC is quote-subscribed, the current bar is processed once, and XYZ never reaches a strategy adapter.

- [ ] **Step 2: Confirm RED.**

- [ ] **Step 3: Implement runtime order:**

```text
bootstrap prior closes
connect/authenticate one stream
subscribe bars/statuses/lulds wildcards
for each event:
  bar -> discovery -> if newly promoted: REST-prime < current bar; stage quote subscription
       -> if promoted: process current completed bar
  quote -> StatusBook
  status/LULD -> StatusBook and board state
on disconnect/error:
  service.feed_health.begin_recovery()
  reconnect same stream object
  gap-recover promoted symbols
  wait for first fresh event
  service.feed_health.mark_recovered()
continue
write Action Board snapshot after meaningful state change
```

Runtime must catch Ctrl+C and close the socket/ledger cleanly. It must never import a broker/trading order API.

- [ ] **Step 4: Write RED Action Board test.** Assert each row contains `rank,symbol,last_price,direction,action,score,production_status,primary_strategy,supporting_families,entry_trigger,stop,target_1,target_2,rvol,spread_pct,feed_health,conflict,updated_at` and production FIRE rows sort above ARMED/WATCH/research rows.

- [ ] **Step 5: Implement atomic snapshot writer and Streamlit reader.** The Streamlit app reads only the JSON snapshot; it displays feed state/age and a dataframe, refreshes with `time.sleep(2); st.rerun()`, and contains no scanner mutation or order controls.

- [ ] **Step 6: Implement CLI:**

```bash
python scripts/run_live_scanner.py --feed sip --ledger data/live/scanner.db --snapshot data/live/action_board.json
streamlit run scripts/run_action_board.py -- --snapshot data/live/action_board.json
```

Required startup checks: credentials present; leaderboard/evidence path exists; data directory writable; SIP auth/subscription errors are printed without secrets.

- [ ] **Step 7: Full suite/compile; commit.**

---

### Task 5: Manual real-SIP smoke, documentation and Phase 2 release gate

**Files:**
- Create: `.github/workflows/live-scanner-smoke.yml`
- Create: `docs/research/unified_live_scanner_phase2.md`
- Modify: `README.md`
- Test: existing full suite plus smoke command parser tests in `tests/live/test_runtime.py`

**Interfaces:**
- Add `scripts/run_live_scanner.py --transport-smoke-seconds N` mode. This authenticates/subscribes to SIP, counts received control/data events, prints a secret-free summary and exits without starting strategy alerts.

- [ ] **Step 1: Add manual-only workflow.** It must use `workflow_dispatch` only, never `schedule` or `push`, and pass existing `APCA_API_KEY_ID` / `APCA_API_SECRET_KEY` secrets to a 20-second transport smoke. No trading API endpoint is called.

- [ ] **Step 2: Add docs covering:** one-connection constraint; SIP entitlement errors; launch commands; Action Board fields; reconnect semantics; `MISSED_DURING_GAP`; SQLite/JSON locations; shutdown/restart; explicit no-order boundary.

- [ ] **Step 3: Run final repository verification:** `pytest -q`, `python -m compileall -q scanner scripts`, `pip check`, and inspect the full PR diff for `submit_order|place_order|create_order|cancel_order` outside documentation/tests.

- [ ] **Step 4: Open a draft Phase 2 PR and use GitHub Actions as the RED/GREEN runner for each isolated task.**

- [ ] **Step 5: Trigger the manual real-SIP smoke only after all API-free CI is green.** Success requires authentication, confirmed subscription, at least one control message, and either a market-data event or a clean `no_data_during_window` result outside active market traffic. An entitlement/auth error leaves Phase 2 code intact but blocks declaring the real feed production-ready.

- [ ] **Step 6: Do not merge until full CI, manual transport smoke, restart/recovery tests, and execution-boundary review are all green.
