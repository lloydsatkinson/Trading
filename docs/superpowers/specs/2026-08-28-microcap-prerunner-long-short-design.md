# Microcap Pre-Runner Long/Short Research Design

**Date:** 2026-08-28

## Goal

Extend the existing intraday small-cap tournament into a microcap-first learning engine that discovers what is measurably different **before** large long runners and shortable failures develop. The system must test both sides independently, optimise transparent rules without leaking later data, and report when no robust edge exists.

## Scope

- Research/paper validation only; no live order routing.
- Price/liquidity microcap proxy initially: prior close $0.75-$20. True point-in-time market cap/float is not available in the current Alpaca bar dataset and must never be fabricated.
- Both LONG and SHORT are first-class research sides and are never pooled for performance selection.
- Primary discovery window: premarket through 09:35 ET, with later continuation/failure setups retained as separate families.
- Preserve the external August 12-27, 2026 block as untouched while development continues on data ending August 11.

## Core hypothesis

The useful edge is more likely to be **abnormal participation plus structure** than a named breakout pattern. We therefore measure features frozen at 09:25, 09:29, 09:31, 09:32, 09:33, 09:34 and 09:35 ET and ask what those snapshots predict afterwards.

## Signal-time features

Every snapshot is computed using bars at or before its freeze timestamp only. Candidate features include:

- premarket gap, range, volume, dollar volume, distance from PM high;
- exact-window opening RVOL versus the same elapsed minutes over prior sessions;
- RVOL slope and minute-volume acceleration;
- opening impulse, HOD extension, pullback depth and gain retention;
- session VWAP distance and close location;
- recent range contraction/expansion and volume contraction;
- prior-volume context and prior multi-day return when available;
- suspected halt/gap context from missing regular-session minute intervals.

Point-in-time float, market cap, NBBO spread, catalyst text, dilution inventory, borrow/locate availability and locate fees are explicitly marked unavailable until a valid source is joined.

## Outcomes

For every snapshot, record future path labels rather than only a binary up/down result:

- executable next-bar reference price;
- LONG MFE and MAE;
- SHORT MFE and MAE;
- whether +10%, +20%, +30% and +50% favourable excursions occur;
- time to each threshold;
- future HOD/LOD and time to HOD/LOD where available.

These labels may be used for evaluation only, never as signal-time filters.

## Controls and sampling

The existing full-day coarse selector is acceptable for downloading a superset for strategy replay but is biased for pre-runner feature discovery because same-day H/L helps choose minute histories. The new pre-runner dataset must therefore include deterministic controls chosen using **prior information only**. Eventual large movers may be intentionally oversampled as cases, but each case is paired with non-event controls matched approximately by prior price/liquidity bands. Training reports must use weighting or stratified metrics so oversampling does not masquerade as real-world precision.

## Optimisation

Threshold discovery occurs on development data only. Validation is used to reject unstable rules. An internal test period is opened only after a candidate rule is frozen. The external August 12-27 block remains untouched.

Optimisation is transparent rather than a black-box maximisation of in-sample PF:

1. measure single-feature lift and coverage;
2. generate thresholds from development quantiles only;
3. test a bounded set of two/three-feature combinations;
4. replay next-bar entries with stop/target/hold grids;
5. stress at baseline and 2x friction;
6. retain a Pareto frontier across PF, expectancy, trades/day and drawdown;
7. report long and short frontiers separately.

No rule is repaired against a period on which it failed.

## Execution model

Entries use the next available minute open plus modelled adverse slippage. Stop/target ambiguity inside one minute is stop-first. If a missing-minute gap or suspected halt reopens through a stop, the exit is the adverse next-print/open price rather than an impossible stop fill. Short results remain research-only until point-in-time borrow/locate and fees are available.

## Artifacts

The remote study should emit compact artifacts including:

- snapshots and path labels;
- long/short feature-lift tables;
- candidate and frozen rule tables;
- execution-grid results under baseline and 2x cost;
- Pareto frontiers for each side;
- rejected-rule log;
- limitations/coverage manifest;
- human-readable summary.

Raw/bulky minute history remains out of Git.

## Success criteria

A candidate is interesting only if it has positive cost-adjusted expectancy, useful sample size/frequency, and materially stable PF across chronological development/validation/internal-test periods and under cost stress. High PF from a tiny number of trades or a few extreme winners is not sufficient. No strategy is promoted to live trading by this research engine.