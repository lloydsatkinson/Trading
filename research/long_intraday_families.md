# Intraday Long Research Families

Research status: hypotheses to test, not live-trading approval.

## Objective

Build independent long setups that can trigger across the full U.S. session rather than relying only on the opening move.

## Core families

1. RUNNER_VWAP_RECLAIM — large-volume runner flushes, selling is absorbed, then VWAP / pain level is reclaimed.
2. SBE_MIDDAY_EXPANSION — impulse -> retained gains -> volume/range contraction -> secondary breakout.
3. HIGHEST_VOLUME_DAY_BREAKOUT — exceptional cumulative participation -> long consolidation -> PMH/HOD breakout.
4. CATALYST_FIRST_PULLBACK — fresh catalyst -> opening impulse -> orderly first pullback -> continuation.
5. AFTERNOON_HOD_CONTINUATION — morning leader holds above VWAP, compresses, then breaks HOD after 13:30 ET.
6. EOD_SHORT_COVER_REVERSAL — former/current runner stops falling, reclaims key level late, and accelerates into the close.

## SSR as a long-side feature

Regulation SHO Rule 201 is commonly called SSR / the alternative uptick rule. When a covered stock falls 10% or more from the prior regular-session close and the listing market triggers Rule 201, short-sale orders generally cannot be executed or displayed at a price less than or equal to the current national best bid, subject to exceptions. The restriction then applies for the remainder of that trading day and the following trading day while an NBBO is disseminated.

SSR is NOT a standalone buy signal. Long-side research should treat it as a context variable that may change the supply/demand mechanics after a sharp decline.

### Required SSR features

- ssr_active
- ssr_triggered_today
- ssr_next_day
- ssr_trigger_time
- ssr_trigger_price
- distance_to_ssr_trigger_pct before activation
- retriggered_on_next_day
- minutes_since_ssr_trigger
- price_vs_vwap_after_ssr
- higher_low_after_ssr
- volume_after_ssr
- downside_displacement_per_sell_volume
- reclaim_volume_ratio

### Long strategies to test with SSR

#### SSR_FLUSH_RECLAIM

Candidate:
- high-RVOL small-cap runner or former runner;
- falls enough to trigger Rule 201 during regular hours;
- heavy sell volume fails to keep producing new lows;
- forms higher low / absorption zone;
- reclaims VWAP, prior breakdown level or high-volume node;
- renewed upside volume confirms demand.

Hypothesis: once downside aggression stops working, the Rule 201 price test may reduce the ability of new shorts to press bids directly, making a genuine reclaim more asymmetric. This must be proven empirically; long liquidation can still overwhelm the stock and short sales are still possible at permissible prices.

#### SSR_DAY2_RECLAIM

Candidate:
- Rule 201 was triggered the prior trading day;
- restriction remains active on current day;
- stock opens weak / flat but refuses to make meaningful new lows;
- early support holds;
- VWAP / prior-close / premarket-high reclaim with rising volume.

Hypothesis: Day-2 SSR plus accumulated short interest / trapped inventory may create a cleaner continuation or squeeze setup than Day-1 frontside chasing.

#### SSR_BACKSIDE_TO_FRONTSIDE_FLIP

Candidate:
- prior frontside trend broke;
- stock triggered SSR during flush;
- backside selling loses efficiency;
- first meaningful reclaim of VWAP plus broken trend pivot occurs;
- price holds the reclaim for multiple completed bars.

This is the long mirror of the backside short: the model waits for evidence that the fade thesis has stopped working before entering.

## Interaction tests

Do not evaluate SSR only as yes/no. Test interactions:

- SSR x RVOL
- SSR x float / turnover
- SSR x catalyst quality
- SSR x runner age
- SSR x retained gain after flush
- SSR x VWAP reclaim
- SSR x volume contraction before reclaim
- SSR x time of day
- SSR x prior-day extreme gain
- SSR x historical borrow tightness where point-in-time data is available

## Guardrails

- Rule 201 trigger is based on listing-market determination during regular trading hours, not an inferred premarket drop.
- Do not assume SSR means shorts cannot short; it is a price-test restriction, not a ban.
- Do not treat an SSR badge as proof of a squeeze.
- Use next-bar / quote-aware execution and realistic spread/slippage.
- Halt/gap risk remains fully active.
- Separate Day-1 SSR-trigger events from inherited Day-2 SSR events.

## Priority ranking

1. SSR_FLUSH_RECLAIM
2. RUNNER_VWAP_RECLAIM
3. SBE_MIDDAY_EXPANSION
4. SSR_DAY2_RECLAIM
5. HIGHEST_VOLUME_DAY_BREAKOUT
6. AFTERNOON_HOD_CONTINUATION
7. CATALYST_FIRST_PULLBACK
8. EOD_SHORT_COVER_REVERSAL

Promote only on out-of-sample PF, expectancy, frequency, drawdown, cost stress and regime stability.