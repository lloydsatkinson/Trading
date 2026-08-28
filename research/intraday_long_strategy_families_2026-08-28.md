# Intraday Long Strategy Families — 2026-08-28

Objective: identify independent US small-cap long setups that can trigger across the full regular session. These are research candidates, not approved live edges.

## Priority order

1. RUNNER_VWAP_RECLAIM — 09:45–15:30 ET
   - Existing runner with strong abnormal volume / catalyst context.
   - Early or midday flush attracts sellers/shorts but downside displacement decelerates.
   - Trigger only after VWAP reclaim + hold + break of reclaim-bar/pain pivot on renewed volume.
   - Key features: down-volume per unit downside, higher low, VWAP distance/reclaim, volume acceleration, prior runner age.

2. SBE_MIDDAY_EXPANSION — 10:00–15:00 ET
   - Meaningful impulse, high retained gain, 20–90 minute base, range/volume contraction.
   - Trigger on frozen local pivot break with breakout volume expansion and immediate follow-through.
   - Existing SBE evidence makes post-10:00 triggers particularly worth validating.

3. HVD_BREAKOUT — 10:00–15:30 ET
   - Session/premarket volume already near or above prior high-volume-day percentiles.
   - One strong impulse, long consolidation above VWAP, then PMH/HOD/local-pivot breakout.
   - Key variable is abnormal participation, not simply percent gain.

4. CATALYST_FIRST_PULLBACK — 09:35–11:30 ET
   - Verified fresh catalyst, strong opening impulse, first orderly pullback above VWAP.
   - Pullback volume contracts; confirmation bar closes strong; trigger above micro pivot.
   - Avoid first-spike chase; next-bar execution only.

5. AFTERNOON_HOD_CONTINUATION — 13:30–15:50 ET
   - Strong first-half return, high volume/volatility, price above VWAP and retains morning gains.
   - Tight afternoon shelf under HOD; trigger on HOD/local pivot break with renewed volume.
   - Market/tape regime should be included because late-day intraday momentum is stronger on high-volume/high-volatility days.

6. EOD_SHORT_COVER_REVERSAL — 15:25–15:55 ET
   - Prior/current runner that sold off intraday without a fresh negative catalyst.
   - Downside stalls, short-cover pressure appears, and price reclaims a late-day micro pivot / VWAP where feasible.
   - Treat as a separate reversal model; do not mix with momentum-continuation rules.

## Validation rules

- All entries are next-bar / trigger-after-completed-bar; no signal-bar fills.
- Separate development, validation, holdout and final unseen blocks.
- Stress at multiple spread/slippage assumptions and preserve same-bar stop-first handling.
- Require trade count, PF, expectancy, max drawdown, MFE/MAE, time-to-expansion, monthly stability and ticker concentration.
- Do not promote a strategy only because a few parabolic winners create a high PF; cap winners in robustness tests.
- Prefer a portfolio of uncorrelated intraday states over one strategy forced to trade all day.
