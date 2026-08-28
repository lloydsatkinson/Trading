# SerClick Remote Research Design

## Purpose

Move the SerClick/Leo small-cap long research loop from a local Windows run into the `lloydsatkinson/Trading` repository so research can execute on GitHub Actions and surface compact, decision-useful news instead of requiring manual Python operation.

## Locked research principles

- Leo is an upstream participation/liquidity selector, not an entry by itself.
- Keep the original Leo thresholds unchanged for the baseline: PM high / prior close > 1.20 with > $10m PM dollar turnover; HOD through 09:59 / prior close > 1.20 with > $5m 09:30-09:59 dollar turnover.
- Preserve chronological, no-lookahead signal construction and next-executable-minute-bar entry with 25 bps slippage.
- Treat 09:30-10:30 as an observation/trap-building window, not a preferred execution window, until new evidence overturns the baseline.
- Prioritise LEO BOTH ignitions from 10:30-15:00 and 16:00-20:00 for execution research.
- The historical 2026-06-03 to 2026-08-27 final 15-session block has already been inspected and is no longer an untouched holdout. New data from 2026-08-28 onward is the prospective holdout.
- Never commit Alpaca credentials or live-order code. This repository is research/backtest/paper-validation only.

## Architecture

### 1. Baseline scanner

Retain the audited SerClick state machine: DISCOVERED -> SHORTS_BUILDING -> ABSORPTION -> ARMED -> IGNITION. Historical market data comes from Alpaca SIP; trading-account endpoints are used only for calendar/assets.

### 2. Path-aware replay

For every first ignition, replay actual one-minute bars from the entry timestamp against a fixed stop/target/hold grid. If stop and target are both touched in the same minute, assume the stop occurred first. This deliberately avoids optimistic intrabar ordering.

The initial grid is stops 3/5/7/10%, targets 5/10/15/20/30%, and maximum holds 30/60/120 minutes.

### 3. Research variants

Report at least these variants separately:

- ALL
- LEO_BOTH_ALL
- LEO_BOTH_MIDDAY (10:30-15:00)
- LEO_BOTH_AH (16:00-20:00)
- MORNING_OBSERVATION (09:30-10:30)

Do not combine midday and after-hours merely to increase sample size; their liquidity regimes differ.

### 4. Shortlist/news layer

For the latest completed session, rank names by state and Leo population. A research signal is marked `TRADABLE_RESEARCH_SIGNAL` only when the name is LEO BOTH and its first ignition is in 10:30-15:00 or 16:00-20:00. LEO BOTH names that have reached ABSORPTION/ARMED/IGNITION without a qualifying execution window are `WATCH`. Morning ignitions are `OBSERVE_TRAP`.

Generate compact artifacts:

- `latest_results.json`
- `latest_shortlist.csv`
- `news.md`
- fixed-horizon summary
- replay grid and replay summary

### 5. Remote execution

Two GitHub Actions workflows:

- Daily: after the full US extended-hours session, run one completed session and publish the latest shortlist/news artifact.
- Weekly/manual: run the full 60-session study, path-aware replay and validation summaries.

GitHub Actions reads Alpaca credentials only from repository secrets `APCA_API_KEY_ID` and `APCA_API_SECRET_KEY`.

## Error handling

- Invalid historical Alpaca symbols are removed one at a time and the valid remainder is retried.
- 429 responses retry with bounded backoff.
- Missing minute cache for a signal produces no replay row rather than fabricated data.
- Workflow artifacts and step summaries make failures inspectable remotely.

## Validation

Unit tests cover Leo gates, invalid-symbol recovery, `.env` credential loading, conservative same-bar replay ordering, target/stop/time exits, variant filters, profit factor, replay summaries and shortlist ranking. Every GitHub Action runs the test suite before market-data work.

## Success criteria

The system is successful when the repository can run without the user's PC, produces reproducible daily/weekly research artifacts, preserves the Leo baseline without hindsight-tuning, and supports prospective evaluation of whether LEO BOTH midday/AH variants retain profit factor and expectancy on new data.
