# Merciless-Q Research Design

## Goal

Add a mechanically defined Merciless Markets / RelentlessTrader-inspired research family to the existing Trading Research Lab, focused on whether repeated hyper-scalping locations in volatile US micro-cap and small-cap momentum names retain positive expectancy after realistic adverse execution assumptions.

## Research question

The public Merciless Markets material describes many named setups, but the common structure is more compact: a stock-in-play experiences an abnormal momentum impulse, then presents one or more short-duration liquidity/reset events that may re-expand. The research must test that common structure rather than curve-fit every named chart pattern independently.

V1 therefore asks four questions:

1. Does an explosive first move followed by an orderly, shallow reset have positive continuation expectancy?
2. Does repeated testing/absorption of a local high create a higher-quality breakout than a first-touch breakout?
3. Does a failed downside move back through VWAP or a local pivot create a distinct trap/reversal edge?
4. How many repeated scalp opportunities on the same symbol remain profitable before expectancy decays, and at what execution friction does the edge disappear?

## Scope

V1 adds one strategy family, `MERCILESS_Q`, with four mechanically distinct variants:

- `MMQ_FIRST_PULLBACK`: first strong impulse, controlled pullback/contraction, then re-expansion.
- `MMQ_MICRO_BREAKOUT`: repeated local-high tests / flat-top compression followed by volume-backed breakout.
- `MMQ_VWAP_RESET`: strong runner pulls back into or slightly through VWAP, retains a material fraction of the impulse, then reclaims.
- `MMQ_TRAP_RECLAIM`: failed downside break / bear-trap style reclaim after an established runner regime.

The remaining public MMU labels (ABCD/W, cup-and-handle, wedge, red-to-green, panic flush, halt trade, whole/half-dollar, 5-minute pullback and related variants) remain documented hypotheses for later ablation work. They are not separately parameterized in V1 because many collapse onto the same impulse/contraction/reclaim primitives and would multiply the search space.

## Candidate universe

Merciless-Q reuses the existing broad candidate universe and chronological split logic. It must not expand the historical universe using future-known market-cap data.

A candidate must have:

- prior close within the existing multistrategy price bounds;
- broad gap/activity qualification from `MultiStrategyStudy`;
- contemporaneous market-cap handling consistent with the existing research lab;
- opening RVOL when history is available, otherwise the value remains unknown rather than imputed.

Merciless-Q may further reject a broad candidate using its own stock-in-play gates but must not fetch a different universe after seeing later intraday outcomes.

## Feature model

Merciless-Q derives all V1 features only from completed bars available at signal time.

### Stock-in-play / impulse features

- gap percent versus prior close;
- premarket dollar turnover;
- opening RVOL;
- running extension versus prior close;
- impulse percent from prior close;
- impulse velocity in percent per minute;
- dollar-volume expansion;
- distance from HOD / premarket high.

### Structure features

- pullback depth from local peak;
- retained gain: `(pullback_low - prior_close) / (peak - prior_close)`;
- contraction duration;
- range contraction versus impulse range;
- volume contraction versus impulse volume;
- upper-wick ratio and lower-wick ratio;
- close-location value;
- number of local-high tests;
- local range efficiency / net progress versus gross range;
- VWAP distance and VWAP slope.

### Tradability score

A 0-100 `mmq_score` is emitted with every Merciless signal. The score is a transparent heuristic used for segmentation, not a learned model and not a proof of edge.

Initial components:

- stock-in-play quality: 25 points;
- first-move / momentum quality: 20 points;
- reset / consolidation quality: 20 points;
- re-expansion confirmation: 15 points;
- tradability / efficiency: 15 points;
- catalyst/context placeholder: 5 points.

Because historical quote-level spread is not guaranteed in the existing cache, V1 tradability uses bar-derived proxies: wickiness, efficiency, range-to-price, volume and turnover. No synthetic bid/ask spread is invented. Quote/tape features are a later extension when a trustworthy historical source is connected.

## Signal timing and no-lookahead rules

- A setup candle must complete before a signal exists.
- Entry is the next executable one-minute bar open, using the same slippage repricing as the rest of the research lab.
- No feature may use later bars, the session close, the eventual HOD, or future market-cap/catalyst information.
- Same-minute stop/target ambiguity remains stop-first through the shared replay engine.
- Regular Merciless-Q replay ends at 16:00 ET.

## Repeat-entry model

Unlike the existing single-location research families, Merciless-Q may emit several valid entries on the same symbol/session.

Every signal must include:

- `sequence_number`: 1-based order of Merciless-Q entries for that symbol/day;
- `minutes_since_prior_signal`;
- `runner_age_minutes`: minutes since the first qualifying impulse;
- `mmq_score`;
- setup-specific metadata.

To prevent one-minute signal spam, V1 applies a configurable cooldown after each emitted signal and requires a fresh structural reset before another same-variant entry can fire.

The research runner must preserve these repeated signals rather than deduplicating them as long as their `entry_timestamp` differs.

## Friction and repeatability analytics

Existing 10/25/50/75/100 bps entry-slippage replay remains the common comparison baseline.

Merciless-Q adds two summary artifacts:

### `merciless_sequence_summary.csv`

Grouped by variant, direction, split and sequence-number bucket (1, 2, 3, 4, 5+):

- number of signals;
- mean/median return under the baseline research rule where available;
- profit factor;
- win rate;
- mean/median peak return;
- median minutes to peak.

The summary must make it possible to see whether the first, second or later re-entry is the actual edge.

### `merciless_friction_break_even.csv`

For each variant/direction/split, compute profit factor and expectancy at every shared slippage level and report the highest tested slippage with PF >= 1.0 and PF >= 1.25. This is a stress metric, not a claim that basis-point slippage perfectly models real Level-II execution.

## Integration

`Merciless-Q` becomes a fourth selectable family in `scripts/run_strategy_research.py`:

- CLI accepts `--strategy merciless` and includes it in `--strategy all`;
- `generate_price_volume_signals` invokes the Merciless generator from the same cached minute bars and candidate contexts;
- signal rows use strategy id `MERCILESS_Q` and the existing `SignalRecord` schema;
- all existing replay, peak timing, market-cap segmentation and validation-led ranking remain shared;
- `news.md` lists Merciless-Q and includes a compact repeat-entry section when data is present.

## Configuration

Create `MercilessConfig` with deliberately broad, documented research defaults rather than optimized thresholds. Initial defaults:

- `min_price = 0.50`
- `max_price = 30.00`
- `min_gap_pct = 0.10`
- `min_pm_dollar_turnover = 1_000_000`
- `min_opening_rvol = 2.0`
- `min_impulse_pct = 0.15`
- `min_impulse_velocity_pct_per_min = 0.01`
- `min_retained_gain = 0.55`
- `max_pullback_fraction = 0.45`
- `min_contraction_bars = 2`
- `max_contraction_bars = 12`
- `min_breakout_volume_ratio = 1.20`
- `max_upper_wick_ratio = 0.55`
- `min_clv = 0.55`
- `cooldown_bars = 3`
- `max_signals_per_symbol = 8`
- `slippage_bps = 25.0` for emitted reference entry price only; the shared replay still reprices across the full grid.

These defaults are hypothesis-generation gates. Any tuned rule selection must occur only inside development/validation data and must not use locked test or forward data.

## Tests

Add deterministic synthetic-bar tests covering:

1. no signal before a minimum impulse exists;
2. first-pullback signal fires only after contraction and next-bar entry is used;
3. excessive wickiness blocks an otherwise valid breakout;
4. VWAP reset/reclaim does not use future bars;
5. repeated entries receive sequence numbers and respect cooldown;
6. runner caps `max_signals_per_symbol`;
7. CLI accepts `merciless` and `all` includes it;
8. repeatability and friction summaries calculate expected sequence buckets and break-even slippage.

## Non-goals

- No live order routing.
- No claim that one-minute OHLC can reproduce Level-II fills, partial fills or latency.
- No fabricated historical spread/borrow/SSR data.
- No separate optimized rule for every MMU course pattern in V1.
- No use of locked test/forward data to choose thresholds or score weights.

## Success criteria

V1 is complete when Merciless-Q can be selected in the unified runner, generates no-lookahead repeated signals from cached minute data, replays through the same execution grid as the other strategies, produces sequence/friction artifacts, and passes the full API-free test suite. Statistical success is a later empirical result: the code is valid even if Merciless-Q ultimately shows no robust edge.