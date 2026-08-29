# Multi-Strategy Microcap / Small-Cap Research Framework Design

Date: 2026-08-29
Repository: `lloydsatkinson/Trading`
Status: Approved in chat for design; implementation not yet started.

## 1. Objective

Extend the existing Trading Research Lab from a SerClick/Leo-focused research codebase into a shared, multi-strategy intraday research framework for US micro-cap and small-cap equities.

Primary research universe:

- Micro-cap: $50M-$300M market cap.
- Small-cap: $300M-$2B market cap.
- US listed common equities only.
- High-relative-volume / high-dollar-turnover environments are mandatory for candidate formation.
- Research and paper/backtest validation only; no live order routing is added by this project.

The framework must answer one question consistently across strategies: which mechanically defined setups produce robust out-of-sample expectancy after realistic execution assumptions?

## 2. Design Principles

1. Shared infrastructure, independent signals. Market data, universe construction, features, execution simulation, validation, reporting and artifact generation are shared. Strategy-specific logic is isolated.
2. No lookahead. Features and entries may use only information available at or before the simulated decision timestamp.
3. Chronological validation. Development, validation, locked test and prospective-forward periods remain separate.
4. Execution-aware research. A theoretical signal is not considered tradable unless it survives spread/slippage, next-bar execution, liquidity and halt-risk assumptions.
5. Regime decomposition. Results must be segmented by market cap, float, gap, RVOL, price, time of day, direction and liquidity.
6. Strategy comparison uses one schema. Every strategy reports the same core metrics so results are comparable.
7. Existing SerClick/Leo behaviour remains reproducible during migration.
8. Parameter grids are research hypotheses, not proof. No threshold is labelled an edge until it survives validation.

## 3. Target Architecture

```text
Trading/
├── scanner/
│   ├── core/
│   │   ├── universe.py
│   │   ├── market_data.py
│   │   ├── features.py
│   │   ├── execution.py
│   │   ├── replay.py
│   │   ├── validation.py
│   │   └── models.py
│   │
│   ├── strategies/
│   │   ├── orb_stocks_in_play/
│   │   │   ├── config.py
│   │   │   └── strategy.py
│   │   ├── vwap_momentum/
│   │   │   ├── config.py
│   │   │   └── strategy.py
│   │   └── serclick_leo/
│   │       ├── config.py
│   │       └── strategy.py
│   │
│   └── portfolio/
│       └── strategy_ranker.py
│
├── scripts/
│   ├── run_strategy_research.py
│   └── run_remote_pipeline.py
│
├── tests/
├── docs/research/
└── .github/workflows/
```

The existing `scanner/serclick` package is not deleted at the start. Shared components are extracted incrementally, with compatibility tests ensuring the established SerClick research outputs remain reproducible.

## 4. Shared Data Model

### 4.1 Symbol-day candidate record

Each strategy consumes a common candidate record with, where available:

- date
- symbol
- prior close
- market cap
- market-cap bucket
- free float / shares outstanding
- price bucket
- premarket high / low
- premarket volume
- premarket dollar turnover
- premarket gap %
- premarket volume as % of float
- opening dollar volume
- relative volume versus same time-of-day history
- 20-session median daily dollar volume
- spread proxy / quoted spread when available
- VWAP
- ATR / realised intraday volatility
- session high / low known to current timestamp
- catalyst/news classification when a reliable timestamped source is available
- halt/LULD metadata when available

Missing float or news data never causes silent imputation. The field is marked unknown and results are segmented accordingly.

### 4.2 Signal record

Every strategy emits the same minimum signal schema:

- strategy_id
- variant_id
- symbol
- date
- direction
- signal_timestamp
- reference_price
- entry_timestamp
- entry_price_raw
- entry_price_slipped
- stop_reference
- setup_quality fields
- market-cap bucket
- float bucket
- gap bucket
- RVOL bucket
- time-of-day bucket
- catalyst class

### 4.3 Replay record

Each entry is replayed with:

- stop rule
- target rule
- maximum hold minutes
- exit reason
- exit timestamp
- raw return
- slippage-adjusted return
- R multiple
- MFE
- MAE
- maximum adverse spread proxy
- halt encountered flag
- P&L for fixed example position sizes

## 5. Universe and Liquidity Gates

Default research universe is intentionally broad enough to discover the edge while excluding obviously non-tradable prints.

Initial hard gates:

- market cap: $50M-$2B when a date-valid market-cap snapshot exists;
- price: $1-$30 initial grid, with price buckets retained for analysis;
- common equities only; exclude ETFs, funds, warrants, rights and preferred shares where asset metadata supports this;
- high-activity requirement must be met by the strategy-specific candidate rules;
- candidate rows with unknown market cap remain separately tagged rather than backfilled from future knowledge.

Liquidity is treated as a research dimension rather than one global threshold. The engine records spread and dollar-turnover buckets so we can identify where expectancy disappears after execution costs.

## 6. Strategy 1: Stocks-in-Play 5-Minute Opening Range Breakout

### 6.1 Core hypothesis

Stocks experiencing abnormal overnight information arrival and exceptional opening participation undergo a short period of price discovery in which a confirmed break of the first five-minute range can persist further than ordinary stocks.

### 6.2 Candidate gates

Initial hypothesis grid, to be validated rather than assumed:

- market cap: $50M-$2B;
- premarket gap absolute value: test 5%, 8%, 10%, 15%, 20%+;
- premarket dollar turnover: test $1M, $2M, $5M, $10M+;
- first-5-minute dollar turnover: test relative to 20-session same-window median at 3x, 5x, 10x+;
- opening RVOL: minimum research grid 3x, 5x, 10x;
- optional float-rotation buckets: <10%, 10-25%, 25-50%, 50-100%, >100% of float traded;
- catalyst class recorded, but catalyst is not initially mandatory so that price/volume-only performance can be measured separately.

### 6.3 Long trigger

At 09:35 ET, define the 09:30-09:34:59 opening range.

Initial long variants test:

- price breaks opening-range high after 09:35;
- breakout bar closes above opening-range high rather than merely wicking through it;
- price is above session VWAP at confirmation;
- breakout bar volume is >= 1.5x, 2x or 3x the median one-minute volume of the preceding five completed one-minute bars;
- close location value in the breakout bar is in the upper 25% or upper 40% of the bar;
- next executable one-minute bar is used for simulated entry.

Alternative pullback variant:

- first breakout occurs;
- price retests the opening-range high without closing more than a configurable tolerance below it;
- a subsequent one-minute bar reclaims and closes above the range high;
- entry occurs on the next executable bar.

### 6.4 Short trigger

Short variants are tested independently and never pooled with long results.

Two initial variants:

1. Negative-gap ORB: break and close below the five-minute opening-range low while below VWAP.
2. Failed-gap reversal: positive gap, failed opening-range-high attempt, VWAP loss, then break/close below the opening-range low.

Short availability/borrow constraints are not assumed solved by the backtest; the result is labelled signal expectancy unless historical locate availability can be modelled.

### 6.5 Risk and exits

Replay grid includes:

- structural stop beyond opposite side of trigger bar;
- stop beyond opening-range midpoint;
- stop beyond opening-range opposite boundary;
- percentage stops: 3%, 5%, 7%, 10%, 15%, 20%;
- target grid: 5%, 10%, 15%, 20%, 30%, 40%, 50%;
- R targets: 1R, 1.5R, 2R, 3R, 4R;
- trailing exit on VWAP loss/reclaim against position;
- trailing exit under/over prior two one-minute swing lows/highs;
- maximum hold: 5, 10, 15, 30, 45, 60, 90, 120 minutes and EOD.

## 7. Strategy 2: High-RVOL VWAP Momentum / Reclaim

### 7.1 Core hypothesis

A high-RVOL stock that makes a material impulse, then absorbs profit-taking around VWAP and decisively reclaims it, may reveal persistent demand that is not visible from the initial gap alone.

The strategy is designed to avoid blind chasing of the first vertical move.

### 7.2 Candidate gates

Initial research grid:

- market cap: $50M-$2B;
- positive premarket or opening gap: test 5%, 10%, 15%, 20%+;
- intraday impulse from prior close or session open: test 10%, 15%, 20%, 30%+;
- premarket/opening dollar turnover: $2M, $5M, $10M+;
- RVOL: 3x, 5x, 10x+;
- pullback must reach or cross session VWAP after the initial impulse;
- candidate must retain a configurable portion of the impulse before reclaim, testing 40%, 60%, 70%, 80%+ retained gain.

### 7.3 Long trigger

One-minute execution logic, with five-minute context retained:

- stock has already satisfied the impulse and RVOL gates;
- at least one completed one-minute bar trades at or below VWAP during the pullback;
- a later one-minute bar closes back above VWAP;
- reclaim bar closes in upper half or upper third of its range;
- reclaim bar volume is tested at >=1.5x, 2x and 3x recent one-minute median volume;
- optional confirmation: next bar does not close back below VWAP;
- entry occurs on the next executable one-minute bar after the selected confirmation rule.

A higher-quality variant requires:

- rising five-minute VWAP slope;
- no new session low during the pullback;
- reclaim occurs above a defined percentage of the initial impulse base;
- spread/liquidity remains inside the tested tolerance.

### 7.4 Short variant

A VWAP rejection / failed reclaim short is researched separately:

- exceptional positive gap/impulse;
- first material loss of VWAP;
- attempted reclaim trades above VWAP but closes back below;
- subsequent confirmation breaks the rejection bar low;
- entry on next executable bar.

Again, borrow availability is a separate live-tradability constraint.

### 7.5 Risk and exits

Replay grid:

- structural stop below reclaim swing low for longs / above rejection swing high for shorts;
- stop beyond VWAP by volatility-adjusted tolerance;
- percentage stop grid: 3%, 5%, 7%, 10%, 15%, 20%, 30%;
- fixed target grid: 5-50%;
- R targets: 1R-4R;
- partial-taking research at 1R or first HOD retest, with remainder trailed;
- VWAP failure exit;
- prior two-bar swing trailing stop;
- maximum hold: 5-120 minutes and EOD.

## 8. Strategy 3: Leo / SerClick Short-Trap Expansion

### 8.1 Core hypothesis

This strategy exploits crowded short participation that fails to push a high-participation stock lower. Absorption near pain levels followed by renewed expansion can force short covering and produce nonlinear upside.

Unlike the first two strategies, this family already has repository-specific evidence and must preserve the currently locked Leo definitions during migration.

### 8.2 Locked upstream Leo gates

Preserve the existing baseline definitions unless a new research variant is explicitly created:

Premarket Leo:

- premarket high / prior close > 1.20;
- premarket dollar turnover > $10M.

10:00 Leo:

- high of day through 09:59 / prior close > 1.20;
- 09:30-09:59 dollar turnover > $5M.

Priority populations remain:

- 09:30-10:30: observation / trap-construction research;
- 10:30-15:00: LEO BOTH priority execution research;
- 16:00-20:00: LEO BOTH after-hours studied separately.

### 8.3 Trigger behaviour

The existing concepts remain the basis of the signal generator:

- shorts-building proxy;
- price absorption;
- pain-level proximity;
- expansion/ignition;
- next executable one-minute bar entry with explicit slippage.

Migration into the shared strategy interface must not silently alter the current definition. Any improved version receives a new `variant_id`.

### 8.4 Risk and exits

Retain the existing variable-stop research grid:

- 3%, 5%, 7%, 10%, 15%, 20%, 30%, 40%, 50%.

Expand common replay reporting to include:

- structural stop candidates based on absorption/pain level;
- target/R grids consistent with the shared engine;
- maximum hold optimisation;
- MFE/MAE;
- market-cap and float segmentation;
- morning, midday and after-hours treated as distinct variants.

## 9. Execution Model

The research engine must never assume fills exactly at a signal candle close.

Baseline execution behaviour:

- signal generated only after a bar is complete;
- entry uses the next executable one-minute bar;
- default fixed slippage baseline preserves the existing 25 bps assumption for comparability;
- replay additional slippage scenarios: 10, 25, 50, 75, 100 bps;
- where quote data exists, slippage can be augmented by observed spread;
- any strategy that loses its edge under realistic micro-cap slippage is downgraded regardless of raw candle-return performance.

Maximum slippage tolerance is not declared globally in advance. For each strategy, reporting must identify the break-even slippage level and the point at which profit factor falls below 1.0 and 1.2.

## 10. Halt and Low-Float Risk Treatment

The engine must flag but not invent certainty around LULD and manipulation risk.

Required risk fields where data permits:

- halt encountered after entry;
- entry immediately before halt;
- post-halt gap against position;
- unusually high float rotation;
- spread expansion;
- volume spikes unsupported by sustained dollar turnover;
- repeated sharp reversals around obvious breakout levels.

No rule should call ordinary volatility a 'market-maker manipulation' event without evidence. Suspicious behaviour is classified as market-quality risk, not proof of intent.

## 11. Validation Protocol

### 11.1 Chronological splits

For each research window:

- development: earliest block;
- validation: subsequent block used for parameter selection;
- locked test: final historical block not used for tuning;
- prospective forward: all sessions after the historical test has been inspected.

The exact split sizes are configurable by session count, but ordering is immutable.

### 11.2 Selection rules

A candidate rule is not promoted merely for high PF on a small sample.

Leaderboard eligibility should require configurable minimum sample thresholds, reported at minimum at n=20, n=50 and n=100 where possible.

Ranking uses a robustness score composed of:

- validation profit factor;
- test profit factor;
- expectancy;
- sample size;
- median trade;
- drawdown;
- slippage resilience;
- consistency across nearby parameter values;
- consistency across market-cap/liquidity subgroups.

No optimisation may read prospective-forward outcomes when selecting parameters.

## 12. Reporting

Every run produces strategy-level and cross-strategy artifacts.

### 12.1 Strategy report

Minimum metrics:

- number of candidate symbol-days;
- number of signals;
- trades/day;
- win rate;
- mean and median return;
- mean and median R;
- profit factor;
- expectancy;
- max drawdown;
- average MFE and MAE;
- maximum adverse excursion tail statistics;
- fixed-position P&L examples;
- break-even slippage;
- max-hold performance table.

### 12.2 Segmentation

Report by:

- micro-cap vs small-cap;
- float bucket;
- price bucket;
- gap bucket;
- RVOL bucket;
- premarket dollar turnover bucket;
- float rotation bucket;
- time-of-day bucket;
- catalyst class;
- direction.

### 12.3 Cross-strategy leaderboard

A common leaderboard compares only like-for-like split states.

Example columns:

- strategy
- variant
- split
- n
- trades/day
- win rate
- expectancy
- profit factor
- median R
- max drawdown
- 25bps PF
- 50bps PF
- 100bps PF
- best validated max hold
- market-cap segment

Historical test and prospective-forward results must be visually distinguished from development/validation results.

## 13. Remote GitHub Actions

Keep current CI, SerClick daily and SerClick 60-day workflows operational during migration.

Add, after implementation:

1. Multi-Strategy Daily Research
   - run the latest-session candidate/signal generation;
   - produce compact latest shortlist and strategy leaderboard artifacts.

2. Multi-Strategy Historical Research
   - manually triggerable and optionally weekly;
   - run configurable session windows;
   - generate replay grids and validation reports.

Credentials continue to live only in GitHub Actions secrets. No API keys are committed.

## 14. Backward Compatibility

Before extracting SerClick shared modules, capture golden outputs from a deterministic fixture/sample.

Migration is accepted only when:

- existing SerClick unit tests pass;
- locked Leo gates are unchanged;
- deterministic fixture candidate/ignition counts are unchanged unless an intentional migration note explains the difference;
- existing remote pipeline entry point remains usable until the new shared runner is verified.

## 15. Testing Strategy

Implementation follows test-driven development.

Required test classes:

- no-lookahead feature tests;
- same-time-of-day RVOL calculations;
- opening-range boundary tests;
- VWAP reclaim/rejection trigger tests;
- next-bar entry tests;
- stop/target same-bar ambiguity tests using a conservative ordering rule;
- slippage application tests;
- market-cap bucket tests;
- chronological split tests;
- SerClick compatibility tests;
- leaderboard eligibility / minimum-n tests;
- prospective-forward isolation tests.

If stop and target are both touched inside the same one-minute candle and tick ordering is unavailable, default to the conservative adverse outcome or mark as ambiguous and report both sensitivity cases. The selected policy must be consistent across all strategies.

## 16. Initial Success Criteria

The implementation is considered technically complete when:

- all three strategy families run through one shared command;
- outputs use one signal/replay/report schema;
- SerClick baseline compatibility is preserved;
- ORB and VWAP signals can be backtested over the same Alpaca SIP session windows;
- market-cap segmentation is produced without historical lookahead;
- slippage sensitivity and max-hold analysis are automated;
- a cross-strategy leaderboard is generated;
- CI tests pass;
- remote workflow can produce downloadable research artifacts.

A strategy is considered research-promising, not 'proven', when it shows positive expectancy and PF > 1 after costs on validation and locked test with adequate sample size and acceptable drawdown. A higher promotion threshold such as PF >= 1.5, n >= 100 and positive prospective-forward expectancy should be evaluated, not hard-coded before seeing distributional evidence.

## 17. Explicit Non-Goals

This project does not initially:

- route live orders;
- claim historical short signals were borrowable;
- infer manipulation intent from price action;
- use future market-cap values to label historical signals;
- optimise against prospective-forward results;
- require a news feed before price/volume-only strategies can be measured;
- discard the existing SerClick research history.

## 18. Implementation Sequence

Implementation should proceed in this order:

1. Add shared models and validation primitives with tests.
2. Add shared execution/replay primitives with tests.
3. Add shared feature calculations and universe helpers.
4. Wrap existing SerClick/Leo logic behind the new strategy interface without changing signal semantics.
5. Implement ORB Stocks-in-Play strategy and tests.
6. Implement VWAP Momentum/Reclaim strategy and tests.
7. Add common reporting and cross-strategy leaderboard.
8. Add shared CLI runner.
9. Add remote GitHub Actions workflow.
10. Run compatibility checks, CI and an initial historical research run.

This sequence minimizes the risk of breaking the only currently validated strategy while creating infrastructure that the new strategies can share.