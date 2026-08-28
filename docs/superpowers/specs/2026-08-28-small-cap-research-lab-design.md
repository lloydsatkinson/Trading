# Small-Cap Research Lab Design

**Date:** 2026-08-28

## Goal

Build a fully automated, cost-aware research framework for long-side US small-cap strategies that searches for the best attainable combination of trade frequency, profit factor, expectancy, robustness and executable liquidity without manufacturing trades or overfitting a final period.

## Operating principles

- Research and paper validation only; no live broker routing.
- Long-side US equities only in the initial lab.
- Signal-time features must not contain future information.
- Every strategy is an independent, named rule set sharing one measurement engine.
- Strategy selection uses chronological development, validation and holdout periods. A later regime is opened only after candidate rules are frozen.
- Costs are applied before PF and expectancy are calculated.
- Sample count and trades/day are first-class metrics; high PF with negligible frequency is not considered sufficient.
- Attractive historical rules that fail a later regime are rejected rather than repaired using that same regime.
- Raw datasets, credentials, API keys and broker secrets never enter the public repository.

## Architecture

`trading_lab/features.py` owns signal-time transformations. `trading_lab/rules.py` defines transparent range-based strategy rules. `trading_lab/metrics.py` owns cost-adjusted performance metrics. `trading_lab/splits.py` assigns chronological periods. `trading_lab/tournament.py` ranks strategies without accessing the final period and separately evaluates frozen candidates. `trading_lab/presets.py` contains named hypotheses. Research documents record frozen rules and evidence without storing raw market data.

GitHub Actions runs regression tests on standard public runners only. No workflow is permitted to use paid larger runners or a paid data upgrade without explicit user approval.

## Strategy families

The lab keeps several hypotheses independent: Catalyst Early Runner, catalyst robustness/frequency variants, Spike-Base-Expansion, Dan Irish secondary expansion, absorption/reclaim and former-runner continuation. A strategy may be promoted in research ranking only if its observed edge survives costs and multiple chronological regimes.

## Metrics and gates

Core outputs are trade count, trades/day, expectancy, win rate and PF. Diagnostic research additionally uses concentration, monthly stability, winner caps, cost stress and bootstrap uncertainty.

The long-run target is not a fixed number of trades. The lab searches the Pareto frontier between frequency and robustness. A candidate advertised as high-frequency should approach at least one trade per trading day; a candidate advertised as high-PF should target PF >= 1.30 after realistic friction. If no rule clears both, the system reports that no qualifying strategy exists.

## Current data methodology

The recovered daily research dataset spans 2025-01-02 through 2026-07-31. It is used as a next-session proxy, not as proof of executable intraday performance. Current chronological research periods are development through 2025-12-31, validation 2026-01-01 through 2026-04-30, holdout 2026-05-01 through 2026-06-30, and the already-observed July 2026 later-regime check.

The existing SBE minute-replay framework remains separate and preserves its own no-lookahead methodology and locked August test conventions. Daily proxy results cannot substitute for minute-level execution validation.

## Promotion status

No strategy is approved for live trading by this design. A candidate must ultimately be rerun using executable intraday/next-open prices, spread/slippage assumptions, and a fresh unseen sample. A forward paper sample is required before any live-trading recommendation.