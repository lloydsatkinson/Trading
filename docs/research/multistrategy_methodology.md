# Multi-Strategy Microcap / Small-Cap Research Methodology

## Purpose

This research layer compares mechanically specified intraday and short-horizon swing strategies under one execution, validation and reporting framework. It is designed to answer whether an apparent edge survives realistic fills, chronological holdouts, nearby execution assumptions and incomplete future-horizon controls rather than merely looking attractive on ideal candles.

## Research universe

Primary known-cap buckets:

- Micro-cap: $50M to below $300M.
- Small-cap: $300M to below $2B.
- US-listed common-equity candidates; warrants/rights/units are excluded where asset metadata permits.

ORB/VWAP retain their original **$1-$30** discovery gate. Dan research has a separate candidate path and is reported by these price buckets:

- `LT_1`: below $1
- `1_2`: $1 to below $2
- `2_5`: $2 to below $5
- `5_10`: $5 to below $10
- `10_20`: $10 to below $20
- `20_50`: $20 to below $50
- `50_100`: $50 to below $100
- `GE_100`: $100+

The broad ORB/VWAP candidate process is intentionally independent from Leo and Dan. A stock can qualify for ORB/VWAP research without satisfying the +20% Leo extension threshold, and enabling Dan cannot broaden the ORB/VWAP price gate.

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

### Dan Irish secondary-move research

This family converts publicly observable continuation ideas into mechanically testable hypotheses. It does **not** claim to reproduce a trader's private rules.

Attribution labels:

- `DAN_DERIVED`: intraday rules mechanically derived from the public pattern concept.
- `DAN_INSPIRED`: swing variants inspired by publicly observable continuation behaviour but requiring additional implementation assumptions.

Current intraday variant:

- `DAN_INTRADAY_SECONDARY`

Current swing variants:

- `DAN_OVERNIGHT_CLOSE_ENTRY`
- `DAN_OVERNIGHT_AH_ENTRY`
- `DAN_OVERNIGHT_NEXT_OPEN`
- `DAN_DAY2_CONTINUATION`
- `DAN_MULTIDAY_COMPRESSION`

The broad V1 candidate grid studies combinations around:

- reference extension / impulse;
- premarket or opening dollar turnover;
- retained gain;
- consolidation duration;
- pullback depth;
- breakout volume ratio.

`setup_id` is retained as part of the reporting/ranking identity whenever present. This prevents two different Dan qualification settings from being pooled merely because they use the same exit rule.

Retained gain is interpreted mechanically as the proportion of the initial gain above prior close that remains at the relevant base/close reference. It is reported explicitly so the strategy can be tested as an incremental filter rather than assumed to be an edge.

## Execution model

Signals may use only completed bars. Entry is the following executable one-minute bar except the explicit next-open swing variant, where Day-0 qualification remains fixed on Day 0 and the first regular-session minute of the next session supplies the entry.

Adverse entry-slippage scenarios for intraday replay:

- 10 bps
- 25 bps
- 50 bps
- 75 bps
- 100 bps

If stop and target are touched in the same one-minute bar, stop is assumed first.

Short returns use the entry-price denominator, symmetric with long returns. Historical borrow/locate availability is not inferred; short results therefore measure signal expectancy unless locate evidence is separately available.

## Intraday risk and exit research

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

ORB/VWAP and Dan intraday replay paths stop before 16:00 ET. SerClick replay paths stop before 20:00 ET. A nominal 240-minute rule can never cross its strategy session boundary.

Exact maximum favorable price and minutes-to-peak are recorded separately from the stop/target outcome so that hold-time research is not restricted to arbitrary fixed horizons.

## Dan swing replay

Swing stop grid:

- 5%, 8%, 10%, 15%, 20%
- structural stop at the signal's recorded stop reference

Swing percentage target grid:

- 5%, 10%, 15%, 20%, 30%, 40%, 50%

Structural-stop R targets:

- 1R, 1.5R, 2R, 3R, 4R

Maximum swing hold horizons:

- 1, 2, 3, 4, 5, 7, 10 regular sessions

For a long trade, if a later session opens below the active stop, the replay uses the first available opening price and labels the exit `GAP_STOP`. It never assumes the historical stop price was fillable through an overnight gap. If the market opens favorably beyond a target, the target fill remains the configured target price rather than granting the full favorable gap.

After an entry that occurs during a regular session, `max_hold_sessions=N` means the terminal time exit is the close of the Nth subsequent regular session unless a stop or target exits first.

Swing replay records at least:

- return and R multiple where defined;
- MFE and MAE;
- trading/calendar days to peak;
- bars held;
- requested hold horizon;
- split-boundary censor flag;
- right-censor flag;
- selection-eligibility flag.

### Censor rule

A swing replay is excluded from rule-selection metrics whenever its requested future horizon crosses a development/validation/test boundary or extends beyond the available historical data.

This means a large apparent return from a trade whose 10-session future is incomplete cannot increase validation expectancy or profit factor. Censor counts are reported separately rather than silently discarded.

## Validation protocol

Chronology is immutable:

1. `development` — hypothesis formation.
2. `validation` — rule selection.
3. `test` — locked historical evaluation.
4. `forward` — prospective evaluation after inspection.

Test and forward results never influence the selection score.

The leaderboard uses the 25-bps validation row for each fixed strategy/variant/setup/rule identity. Its auditable score includes:

- validation profit factor;
- validation expectancy;
- sample-size component;
- validation median return;
- drawdown penalty;
- slippage resilience across the tested execution grid.

Default minimum sample eligibility is 20 validation trades. Reports also expose n>=50 and n>=100 flags. The current production flag additionally requires **validation expectancy >= 5%** at the baseline selection assumption. A high PF on a tiny sample or an expectancy below the production hurdle remains research evidence, not a production-qualified edge.

A 60-session run is an engineering and initial research horizon. It is **not sufficient promotion evidence for 1-10 day swing rules**, because the number of independent complete-horizon observations is materially smaller than the number of Day-0 candidates. Swing promotion requires longer independent history plus prospective forward evidence.

## Evidence labels

Use these labels consistently:

- `HYPOTHESIS`: mechanically specified but not yet validated.
- `VALIDATED`: survived development/validation criteria with adequate sample.
- `LOCKED_TEST`: result from a historical block that was not used to choose the rule.
- `FORWARD`: prospective observation after the relevant historical results were inspected.

External literature or public trader commentary can justify testing a hypothesis but cannot by itself promote a micro-cap implementation to `VALIDATED`.

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
- `price_bucket_summary.csv`
- `retained_gain_summary.csv`
- `swing_hold_summary.csv`
- `overnight_gap_risk.csv`
- `censor_summary.csv`
- `skips.csv`
- `run_meta.json`
- `news.md`

Compact latest outputs are mirrored under `data/latest/` where supported.

## Verification

API-free engineering verification:

```bash
PYTHONPATH=. pytest -q
python -m compileall -q scanner scripts
```

Dan-only research execution with existing Alpaca access:

```bash
python scripts/run_strategy_research.py --strategy dan --feed sip --sessions 60
```

Unified research execution:

```bash
python scripts/run_strategy_research.py --strategy all --feed sip --sessions 60
```

The research command may make market-data API requests when required caches are absent; it is intentionally separate from CI.
