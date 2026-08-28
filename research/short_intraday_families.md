# Small-Cap Intraday Short Research Families

Research status: hypotheses to test, not live-trading approval.

## Priority families

1. POP_AND_DROP — large gapper / runner fails to hold the pop, confirms lower high / VWAP rejection, then fades.
2. BACKSIDE_VWAP_REJECTION — frontside trend objectively breaks, first bounce fails at VWAP / broken trend pivot.
3. FAILED_HOD_BREAK — HOD/PMH breakout fails, closes back under pivot, then failed reclaim confirms supply.
4. DILUTION_OR_OFFERING_FADE — fresh point-in-time financing/dilution evidence plus price-action failure.
5. FIRST_RED_DAY — multi-day parabolic runner confirms first major daily trend break.
6. LATE_DAY_EXHAUSTION — repeated continuation attempts fail late, major support/VWAP gives way after final squeeze.

## Pop-and-drop core

Candidate structure:
- Price roughly $1-$20.
- Gap preferably >=30%; test 30-50, 50-100 and 100%+ independently.
- High premarket volume / turnover.
- Let the first squeeze happen; never short solely because price is extended.
- Require confirmation: failed PMH/HOD reclaim, lower high, VWAP rejection or opening-support loss.

Test exits:
- cover into morning flush;
- 1R/2R/3R targets;
- time stop if downside expansion does not occur quickly;
- optional small core to close where supported by data.

## Short-side execution constraints

- Point-in-time shortable / borrow availability where obtainable.
- Locate/borrow fees modelled explicitly.
- No theoretical entry when borrow is unavailable.
- Rule 201 / SSR state included for every signal.
- Gap-through-stop fills, not perfect stops.
- Conservative halt and post-halt slippage.
- Spread-aware execution and minute-liquidity participation caps.
- Delisted/inactive names retained where possible to reduce survivorship bias.

## SSR interaction

SSR should not automatically invalidate a short, but the strategy must model its effect on execution. Rule 201 activation changes the prices at which short sales can execute/display; therefore compare:
- pop-and-drop with SSR inactive;
- SSR triggered during the drop;
- inherited Day-2 SSR;
- failed bounce short under SSR;
- backside short under SSR;
- theoretical vs actually executable short entries.

## Tournament ranking

Rank by out-of-sample PF after spread/slippage/locate costs, expectancy, trades/day, max drawdown, chronological stability, executable-trade rate, outlier concentration and 2x-cost survival.

Initial target gate: PF >=1.30 at normal modeled cost and >1.05 at 2x cost, positive expectancy across a majority of walk-forward folds, and untouched/forward validation before live approval.