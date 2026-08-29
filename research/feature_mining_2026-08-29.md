# Intraday Feature Mining — 2026-08-29

Source: completed 60-session SIP minute tournament, 2026-05-15 through 2026-08-11. Final 2026-08-12 through 2026-08-27 block remains untouched.

This pass mines only signal/entry-known variables available in the saved trade artifact: signal time, entry vs prior close, structural risk width, prior 4-day return, and prior-close price. Full-day high/low/volume were not used as filters because they would leak future information.

## Frozen candidates for exact rerun

### SSR_FLUSH_RECLAIM_RISK_3_5
- Base family: SSR_FLUSH_RECLAIM long.
- Entry-known structural risk: >=3% and <5% of entry.
- 136 trades / 60 sessions = 2.27 trades/day.
- PF 1.96; expectancy +0.28R; win rate ~49%.
- Development: n=75, PF 1.55, expectancy +0.17R.
- Validation: n=35, PF 2.35, expectancy +0.42R.
- Holdout: n=26, PF 2.86, expectancy +0.41R.
- Approximate 2x-slippage PF from incremental cost adjustment: ~1.55. Exact 2x replay is required before promotion.
- Top winner contributes ~2.5% of positive R; top 5 ~12.5%, so result is not dominated by one outlier.

A narrower entry-location version (entry between -20% and 0% vs prior close, risk 3–5%) produced 122 trades / 2.03 per day with PF 1.84 development, 2.60 validation, 2.11 holdout. This is a secondary candidate only; do not tune further before exact replay.

### FAILED_HOD_BREAK_30_50_MIDDAY
- Base family: FAILED_HOD_BREAK short.
- Signal time: 10:30–13:00 ET.
- Entry: +30% to +50% vs prior close.
- Entry-known structural risk: <10% of entry.
- 97 trades / 60 sessions = 1.62 trades/day.
- PF 1.72; expectancy +0.37R; win rate ~49.5%.
- Development: n=70, PF 1.61, expectancy +0.33R.
- Validation: n=11, PF 2.91, expectancy +0.74R.
- Holdout: n=16, PF 1.61, expectancy +0.32R.
- Approximate 2x-slippage PF from incremental cost adjustment: ~1.41. Exact 2x replay is required before promotion.
- Top winner contributes ~2.3% of positive R; top 5 ~11.5%, so result is not dominated by one outlier.

## High-PF but low-sample lead

FAILED_HOD_BREAK where the stock's prior 4-day return was -50% to -30% produced n=45, PF ~2.61 overall (development 1.77, validation 4.15, holdout 4.18). This sample is too small for promotion and should be treated as a hypothesis, not a rule.

## Discipline
- No final-August data used.
- No full-day outcome fields used as filters.
- Do not add further conditions to these frozen variants before exact normal/2x-cost minute replay.
- Short results remain research-only until point-in-time borrow/locate availability and fees are joined.
- Exact rerun must preserve next-bar entry, pessimistic stop-first ambiguity, slippage, and chronological splits.
