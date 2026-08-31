# Dan Irish Strategy Family Research Design

Date: 2026-08-31
Repository: `lloydsatkinson/Trading`
Status: Approved in chat for design; implementation not yet started.

## 1. Objective

Add a new long-biased Dan Irish research family to the existing Trading Research Lab without duplicating the shared market-data, replay, validation, slippage, hold-time, peak-timing or leaderboard infrastructure.

The family has four independently scored variants:

1. `DAN_INTRADAY_SECONDARY` — intraday secondary expansion after an initial impulse and consolidation.
2. `DAN_OVERNIGHT_STRENGTH` — late-day/after-hours continuation candidate held into the next session.
3. `DAN_DAY2_CONTINUATION` — Day-1 ignition followed by Day-2 retained strength and renewed expansion.
4. `DAN_MULTIDAY_COMPRESSION` — one-to-five-session compression/base after the ignition, followed by a breakout.

The intraday variant is Dan-derived from his publicly described secondary-move process. The overnight and multi-day variants are labelled Dan-inspired unless each rule can be directly evidenced from Dan's own public material. Attribution labels must be preserved in reports.

This remains research/paper validation only. No live order routing is added.

## 2. Reuse Existing Framework

Do not build a separate research stack.

Reuse the existing:

- `scanner/multistrategy/study.py` Alpaca data/cache infrastructure;
- common signal schema used by ORB, VWAP and SerClick adapters;
- next-executable-bar entry discipline;
- adverse entry-slippage scenarios of 10, 25, 50, 75 and 100 bps;
- stop-first treatment when stop and target are touched in the same one-minute bar;
- chronological `development -> validation -> test -> forward` discipline;
- 25-bps validation-led strategy ranking;
- production promotion expectancy hurdle already enforced by the portfolio ranking layer;
- MFE/MAE and exact time-to-peak analysis where applicable;
- market-cap enrichment rules that never backfill future market-cap snapshots onto historical observations;
- API-free CI philosophy and synthetic integration testing.

The current ORB/VWAP broad candidate defaults remain unchanged, including their existing $1-$30 discovery gate. Dan's broader price research is additive and must not silently widen the candidate population used by ORB or VWAP.

The frozen SerClick historical baseline ending 2026-08-27 must remain unchanged.

## 3. Research Universe and Price Buckets

The Dan family must not impose a narrow price ceiling before measurement.

US-listed common equities are segmented into these price buckets using the price observable at the candidate reference point:

- `LT_1`: below $1
- `1_2`: $1 to below $2
- `2_5`: $2 to below $5
- `5_10`: $5 to below $10
- `10_20`: $10 to below $20
- `20_50`: $20 to below $50
- `50_100`: $50 to below $100
- `GE_100`: $100 and above

Price is a research dimension, not a proxy for company size. Every Dan result must also retain market-cap bucket and, when available, float bucket.

Unknown market cap or float remains explicitly `UNKNOWN` rather than being silently imputed.

Below-$1 names are included for research but never pooled with higher-priced names when evaluating execution quality because spreads, halts, dilution risk and microstructure may be materially different.

Dan candidate discovery uses a separate Dan-specific candidate flag/config. It must not change `MultiStrategyConfig.min_price=1.0` or `MultiStrategyConfig.max_price=30.0` for the existing strategies.

## 4. Common Dan Candidate Features

The common Dan candidate layer records enough information for all four variants without forcing the same entry logic.

For each symbol/day, calculate where data permits:

- prior close;
- price bucket;
- market cap and market-cap bucket;
- float and float bucket;
- premarket high, low, volume and dollar turnover;
- premarket/reference gap percentage;
- regular-session HOD and LOD known to the decision time;
- cumulative dollar turnover;
- opening RVOL and available time-of-day RVOL features;
- session VWAP;
- catalyst class and timestamp when a reliable timestamped source exists;
- impulse start price and impulse high;
- impulse return percentage;
- pullback/base low;
- consolidation duration;
- consolidation range as a percentage of impulse;
- breakout level;
- breakout-bar volume relative to recent completed bars;
- close-location value;
- current distance from VWAP;
- session close location within Day-0 range;
- aftermarket high/low/close when available;
- halt/LULD metadata when available.

### 4.1 Retained Gain Ratio

Add a shared research feature named `retained_gain_ratio`.

For long candidates:

`retained_gain_ratio = (reference_price - impulse_start_price) / (impulse_high - impulse_start_price)`

when the denominator is positive.

Example:

- impulse start $2;
- impulse high $6;
- reference price $5;
- retained gain ratio = 3 / 4 = 0.75.

Record retained gain at meaningful checkpoints where data exists, including 10, 20, 30, 60 and 90 minutes after the impulse, regular-session close, aftermarket close/reference, next open, Day 2 close and Day 3 close.

No future checkpoint may be used by an earlier signal decision.

## 5. Variant A — Intraday Secondary Expansion

### 5.1 Hypothesis

A stock with a material catalyst/impulse and exceptional participation that refuses to give back much of the move, then forms a controlled consolidation, may produce a second expansion with better risk definition than chasing the initial spike.

### 5.2 Research Grid

The initial grid tests rather than assumes:

- initial extension/impulse: +15%, +20%, +30%, +50%, +75%+;
- premarket or cumulative dollar turnover: $1M, $3M, $5M, $10M+;
- retained gain ratio: 40%, 50%, 65%, 80%+;
- consolidation duration: 10, 20, 30, 45, 60, 90 minutes;
- pullback depth: 10%, 20%, 30%, 40%, 50% of the impulse;
- consolidation-range contraction relative to the initial impulse;
- location versus VWAP: above, test-and-hold, or below;
- breakout reference: consolidation high, HOD, or premarket high;
- breakout volume: 1.0x, 1.5x, 2.0x recent completed-bar median.

Catalyst class is segmented. It is not silently assumed mandatory when the historical source is unavailable.

### 5.3 Trigger

A long signal may be emitted only after all required bars are complete.

Core mechanical shape:

1. qualifying impulse has occurred;
2. price forms the configured consolidation/base duration;
3. retained-gain and pullback-depth conditions are satisfied;
4. completed confirmation bar closes through the selected breakout reference;
5. volume confirmation meets the chosen rule where required;
6. entry occurs on the next executable one-minute bar.

Structural stop candidates include consolidation low and last completed higher low. Percentage-stop rules remain available as controls.

### 5.4 Intraday Holds

Reuse the existing intraday hold grid:

- 5, 10, 15, 30, 45, 60, 90, 120, 180 and 240 minutes;
- EOD;
- exact same-session maximum favourable price and minutes-to-peak.

Regular-session Dan intraday trades may not cross 16:00 ET unless a separately identified overnight variant signal is created.

## 6. Variant B — Overnight Strength

### 6.1 Hypothesis

A Day-0 momentum stock that closes near its highs while retaining a large portion of its impulse may carry information/positioning pressure into the next session.

### 6.2 Candidate Features

Test the predictive value of:

- Day-0 impulse size;
- total and late-day dollar volume;
- retained gain ratio at 15:30, close and aftermarket reference;
- close location within Day-0 range;
- close versus VWAP;
- distance from HOD;
- catalyst class;
- aftermarket gain retention;
- Day-0 price and market-cap buckets.

### 6.3 Entry Families

Compare independently:

- `DAN_OVERNIGHT_CLOSE_ENTRY`: next executable bar after a completed 15:30-15:59 confirmation;
- `DAN_OVERNIGHT_AH_ENTRY`: after-hours confirmation using only completed after-hours bars;
- `DAN_OVERNIGHT_NEXT_OPEN`: next-session first executable regular-session entry.

These are separate rule identities. They must not be pooled.

Overnight gaps must be modelled as actual next available prices, not as fills at the prior stop level.

## 7. Variant C — Day-2 Continuation

### 7.1 Hypothesis

The highest-quality Day-1 movers may show persistent demand when Day 2 holds a large proportion of the prior move, avoids full mean reversion and then breaks a newly formed range.

### 7.2 Day-1 Qualification

Record and grid:

- Day-1 gap/impulse;
- Day-1 dollar turnover and RVOL;
- Day-1 closing retained gain ratio;
- Day-1 close location;
- Day-1 close versus VWAP;
- catalyst class;
- Day-1 price/market-cap/float buckets.

### 7.3 Day-2 Structure and Trigger

Test Day-2 structures such as:

- morning pullback that holds above a configurable portion of Day-1 gains;
- tight intraday range relative to Day-1 true range;
- higher low versus Day-1 close/base;
- reclaim/hold of Day-2 VWAP;
- break of Day-2 consolidation high;
- break of Day-1 HOD as a separate variant.

Entry occurs only after a completed confirmation bar and on the next executable bar.

Day-2 continuation is a distinct strategy variant, not an extension of an intraday Day-1 replay.

## 8. Variant D — Multi-Day Compression Break

### 8.1 Hypothesis

A strong ignition event followed by one to five sessions of limited giveback and contracting ranges may create a continuation breakout with improved structural risk.

### 8.2 Base Length

Test base lengths independently:

- 1 trading day;
- 2 trading days;
- 3 trading days;
- 4 trading days;
- 5 trading days.

### 8.3 Compression Features

Record:

- percentage of Day-0 impulse retained at each daily close;
- daily true range divided by Day-0 true range;
- volume contraction versus Day 0;
- sequence of daily lows/highs;
- closes versus anchored Day-0 VWAP when computable without lookahead;
- breakout distance to Day-0 HOD;
- cumulative post-Day-0 dilution/news events when a reliable timestamped source is available.

Breakout families include base-high break and Day-0-HOD break as separate rule identities.

## 9. Swing Risk, Exit and Hold Research

Swing replay is separate from the existing same-session minute replay where necessary.

Test maximum hold horizons:

- 1, 2, 3, 4, 5, 7 and 10 trading days.

Test stop families independently:

- structural base low;
- prior-day low;
- Day-0 support reference;
- anchored-VWAP structural reference when available;
- ATR-normalised stop;
- percentage controls: 5%, 8%, 10%, 15%, 20%.

Test exit families independently:

- fixed R targets;
- percentage targets;
- previous-day-low close/break exits;
- base failure;
- anchored-VWAP loss where available;
- trailing multi-day higher-low exit;
- maximum hold.

For overnight and multi-day trades, stops may gap through. Fill at the first executable observed price after the stop becomes violated; do not assume a fill at the stop price.

Record multi-day MFE, MAE, trading-days-to-peak and calendar-days-to-peak.

### 9.1 Split-Boundary Safety for Swing Outcomes

A swing outcome used to choose a rule may not consume price data from a later validation class.

For each replay rule/horizon:

- determine the last session that can be observed while remaining inside the signal's assigned split;
- if the requested maximum hold extends beyond that boundary, mark that replay `boundary_censored=true` and exclude it from parameter-selection summaries for that horizon;
- do not truncate the trade at the split boundary and pretend the truncated return is the requested hold rule;
- test-period prices may never influence development/validation rule selection;
- forward prices may never influence any historical selection;
- reports include counts of boundary-censored signals by variant and hold horizon.

Equivalent purge/embargo logic is acceptable if it produces the same no-leakage guarantee and is covered by tests.

Signals near the final available data date that do not have their full requested future horizon are similarly `right_censored=true` and excluded from complete-horizon metrics.

## 10. Segmentation and Leaderboards

Every Dan variant is reported separately and additionally segmented by:

- price bucket;
- market-cap bucket;
- float bucket when known;
- catalyst class;
- impulse bucket;
- retained-gain bucket;
- RVOL/dollar-turnover bucket;
- base/consolidation duration;
- entry family;
- stop family;
- hold horizon;
- slippage scenario where applicable.

Core comparison metrics:

- trade count;
- win rate;
- expectancy in raw return and R;
- profit factor;
- average/median winner and loser;
- maximum drawdown under the existing strategy-ranking convention;
- MFE and MAE;
- best hold horizon;
- time to peak;
- execution/slippage resilience;
- overnight gap loss distribution for swing variants;
- boundary/right-censor counts.

The Dan family must appear beside ORB, VWAP and SerClick in common research outputs, but each Dan variant keeps its own strategy/variant identity.

## 11. Validation and Promotion Discipline

Preserve the existing chronological split rules:

1. `development` — hypothesis formation;
2. `validation` — parameter/rule selection;
3. `test` — locked historical evaluation;
4. `forward` — prospective observations after inspection.

Test and forward results may never improve selection scores or tune thresholds.

The existing minimum-sample and production promotion rules continue to apply. A spectacular PF from a tiny price/cap bucket is descriptive, not production-ready.

Price buckets must not be collapsed after seeing test/forward results merely to improve reported performance.

Swing results should support longer research windows than the current 60-session intraday baseline. Sixty sessions remains useful for engineering/smoke validation, but promotion evidence for 1-10 day holds should be based on substantially more history where data coverage permits.

## 12. Data and Lookahead Integrity

No signal may use:

- future bars;
- future news timestamps;
- future market-cap snapshots;
- later-session retained-gain checkpoints;
- next-day closing information for an overnight entry;
- price outcomes from a later validation split for selecting a rule in an earlier split;
- survivorship-biased future listing status when avoidable.

Missing historical news/float/cap data is explicitly marked unknown.

Corporate actions and split-adjustment consistency must be checked before swing returns are trusted. The chosen Alpaca adjustment mode must be explicit in run metadata so multi-day returns are auditable.

## 13. Integration Shape

Preferred package layout:

```text
scanner/strategies/dan_irish/
├── __init__.py
├── config.py
├── features.py
├── intraday.py
└── swing.py
```

### 13.1 Candidate Discovery Isolation

Do not widen the existing global `MultiStrategyConfig` price gate.

Add a Dan-specific candidate function/config that can evaluate the full requested price spectrum. The shared study should build the union of symbols required by the selected families while retaining per-family qualification flags, for example:

- `broad_candidate` — current ORB/VWAP qualification using the existing $1-$30 config;
- `dan_candidate` — Dan-specific momentum/activity qualification with no research ceiling other than positive/finite price and tradable common-equity sanity checks.

When `--strategy all` is requested, minute data may be fetched once for the union of qualified symbols, but dispatch must respect family flags:

- ORB/VWAP generators receive only rows with `broad_candidate=true`;
- Dan generators receive only rows with `dan_candidate=true`;
- SerClick remains sourced through its existing adapter/baseline path.

This reuses downloads without changing historical ORB/VWAP candidate populations.

### 13.2 Shared Modifications

Keep changes minimal and focused:

- `scanner/multistrategy/study.py` — compute family-specific candidate flags, union candidate symbols for cache efficiency, expose daily/session history needed by Dan swing research;
- `scripts/run_strategy_research.py` — register `dan`, route family-qualified contexts, and route same-session versus swing replay correctly;
- `scanner/core/models.py` or a focused shared helper — canonical price bucket function;
- `scanner/core/replay.py` only if a clean extension can support multi-session replay without destabilising intraday replay; otherwise add `scanner/core/swing_replay.py`;
- `scanner/core/reporting.py` / ranking layer only where required to add segmentation and censoring fields;
- tests mirror existing API-free synthetic strategy tests.

`scanner/multistrategy/config.py` should retain its current ORB/VWAP min/max price defaults. Dan-specific thresholds belong in `scanner/strategies/dan_irish/config.py`.

Do not refactor unrelated SerClick code.

## 14. Research Outputs

Retain existing outputs and add Dan-specific analytical files where useful.

Existing common outputs remain:

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

Add or extend:

- `price_bucket_summary.csv`
- `retained_gain_summary.csv`
- `swing_hold_summary.csv`
- `overnight_gap_risk.csv`
- `censoring_summary.csv`
- multi-day peak timing fields in common replay/summary output.

## 15. Verification Requirements

Engineering verification remains API-free where possible:

```bash
PYTHONPATH=. pytest -q
python -m compileall -q scanner scripts
```

New tests must demonstrate:

- price bucket boundaries including below $1 and $100+;
- Dan candidate discovery does not change ORB/VWAP $1-$30 candidate behaviour;
- retained gain calculation and zero/invalid denominator handling;
- no signal before consolidation/confirmation is complete;
- next-bar intraday entry;
- overnight entries cannot see next-session future data;
- gap-through-stop behaviour uses first executable observed price;
- Day-2 rules cannot access later Day-2 bars;
- multi-day base-length rules are isolated;
- validation swing outcomes cannot consume locked-test prices;
- incomplete final-date swing horizons are right-censored rather than treated as completed exits;
- separate variant/rule identities in reporting;
- existing ORB/VWAP/SerClick synthetic integration tests remain unchanged and passing;
- the frozen SerClick baseline cut-off remains 2026-08-27.

Market-data research runs remain separate from CI.

## 16. Success Criteria

Implementation is successful when:

1. `--strategy dan` and `--strategy all` can produce Dan signals through the existing research CLI.
2. Intraday and swing Dan variants are statistically isolated in common outputs.
3. All eight price buckets appear in segmentation when observations exist.
4. Retained-gain features are timestamp-safe and auditable.
5. Multi-session replay correctly handles overnight gaps, trading-day hold horizons and split-boundary/right censoring.
6. Existing ORB, VWAP and SerClick candidate populations and outputs remain compatible.
7. No Dan rule is labelled validated until it passes the existing chronology, sample-size and promotion gates.
8. Swing variants remain labelled Dan-inspired unless direct public evidence supports stronger attribution.
