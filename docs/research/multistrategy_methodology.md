# Multi-Strategy Microcap / Small-Cap Research Methodology

## Purpose

This research layer compares mechanically specified intraday strategies under one execution, validation and reporting framework. It is designed to answer whether an apparent edge survives realistic fills, chronological holdouts and nearby execution assumptions rather than merely looking attractive on ideal candles.

## Research universe

Primary known-cap buckets:

- Micro-cap: $50M to below $300M.
- Small-cap: $300M to below $2B.
- Initial price range: $1-$30.
- US-listed common-equity candidates; warrants/rights/units are excluded where asset metadata permits.

The broad ORB/VWAP candidate process is intentionally independent from Leo. A stock can qualify for ORB/VWAP research without satisfying the +20% Leo extension threshold.

Market-cap snapshots are date-sensitive. Historical observations with no contemporaneously captured market cap remain `UNKNOWN`; current values are not backfilled onto older signals.

## Strategy families

### ORB Stocks-in-Play

The first five regular-session minutes define the opening range. Long and short variants require a completed confirmation bar and enter only on the next executable minute. The variants are:

- `ORB_LONG_BREAK`
- `ORB_LONG_PULLBACK`
- `ORB_SHORT_NEGATIVE_GAP`
- `ORB_SHORT_FAILED_GAP`

Gap, premarket dollar turnover, opening RVOL, breakout volume and close-location thresholds are research parameters, not assumed edges.

### High-RVOL VWAP Momentum / Reclaim

The long variant requires a material impulse before the VWAP interaction, a post-impulse pullback to/through VWAP, retained gain and a volume-confirmed reclaim. The short variant requires a post-impulse VWAP loss, failed reclaim/rejection and subsequent breakdown.

Variants:

- `VWAP_LONG_RECLAIM`
- `VWAP_SHORT_REJECTION`

### SerClick / Leo

The existing Leo qualification and SerClick state machine remain the source of these signals. The adapter normalizes the output schema without redefining the signal.

Locked Leo gates remain:

- PM high / prior close > 1.20 and PM dollar turnover > $10M.
- HOD through 09:59 / prior close > 1.20 and 09:30-09:59 dollar turnover > $5M.

The historical SerClick block ending 2026-08-27 has already been inspected and remains frozen. Unified research forces observations from 2026-08-28 onward into `forward`.

## Execution model

Signals may use only completed bars. Entry is the following executable one-minute bar.

Adverse entry-slippage scenarios:

- 10 bps
- 25 bps
- 50 bps
- 75 bps
- 100 bps

If stop and target are touched in the same one-minute bar, stop is assumed first.

Short returns use the entry-price denominator, symmetric with long returns. Historical borrow/locate availability is not inferred; short results therefore measure signal expectancy unless locate evidence is separately available.

## Risk and exit research

Percentage stop grid for ORB/VWAP:

- 3%, 5%, 7%, 10%, 15%, 20%, 30%

SerClick additionally retains 40% and 50% stop research.

Percentage target grid:

- 5%, 10%, 15%, 20%, 30%, 40%, 50%

Each strategy can also use its signal-time structural stop reference with R targets:

- 1R, 1.5R, 2R, 3R, 4R

Maximum hold grid:

- 5, 10, 15, 30, 45, 60, 90, 120, 180, 240 minutes
- EOD

All ORB/VWAP replay paths stop before 16:00 ET. SerClick replay paths stop before 20:00 ET. A nominal 240-minute rule can never cross its strategy session boundary.

Exact maximum favorable price and minutes-to-peak are recorded separately from the stop/target outcome so that hold-time research is not restricted to arbitrary fixed horizons.

## Validation protocol

Chronology is immutable:

1. `development` — hypothesis formation.
2. `validation` — rule selection.
3. `test` — locked historical evaluation.
4. `forward` — prospective evaluation after inspection.

Test and forward results never influence the selection score.

The leaderboard uses the 25-bps validation row for each fixed strategy/variant/rule identity. Its auditable score includes:

- validation profit factor;
- validation expectancy;
- sample-size component;
- validation median return;
- drawdown penalty;
- slippage resilience across the tested execution grid.

Default promotion eligibility requires at least 20 validation trades. Reports also expose n>=50 and n>=100 flags. A high PF on a tiny sample is not considered a validated edge.

## Evidence labels

Use these labels consistently:

- `HYPOTHESIS`: mechanically specified but not yet validated.
- `VALIDATED`: survived development/validation criteria with adequate sample.
- `LOCKED_TEST`: result from a historical block that was not used to choose the rule.
- `FORWARD`: prospective observation after the relevant historical results were inspected.

External literature can justify testing a hypothesis but cannot by itself promote a micro-cap implementation to `VALIDATED`.

## Outputs

The unified runner writes:

- `signals.csv`
- `replay_grid.csv.gz`
- `strategy_summary.csv`
- `market_cap_summary.csv`
- `leaderboard.csv`
- `slippage_summary.csv`
- `peak_timing.csv`
- `best_hold_times.csv`
- `skips.csv`
- `run_meta.json`
- `news.md`

Compact latest outputs are mirrored under `data/latest/`.

## Verification

API-free engineering verification:

```bash
PYTHONPATH=. pytest -q
python -m compileall -q scanner scripts
```

Research execution with existing Alpaca access:

```bash
python scripts/run_strategy_research.py --strategy all --feed sip --sessions 60
```

The research command may make market-data API requests when required caches are absent; it is intentionally separate from CI.
