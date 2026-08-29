# Frozen Intraday Candidate Robustness — 2026-08-29

Source: completed 60-session SIP minute tournament, 2026-05-15 through 2026-08-11. Final 2026-08-12 through 2026-08-27 block remains untouched.

No new filters were added. These checks apply only to the two already-frozen candidates from `feature_mining_2026-08-29.md`.

## SSR_FLUSH_RECLAIM_RISK_3_5

- n=136 / 60 sessions = 2.27 trades/day.
- PF 1.96; expectancy +0.280R; win rate 55.1%; max drawdown 6.76R.
- Development: n=75, PF 1.55, expectancy +0.170R.
- Validation: n=35, PF 2.35, expectancy +0.419R.
- Holdout: n=26, PF 2.86, expectancy +0.411R.
- Trade-bootstrap expectancy 95% CI: +0.102R to +0.457R; median +0.278R.
- Trade-bootstrap PF 95% CI: 1.291 to 2.952; median 1.951.
- Bootstrap P(PF > 1.30): 97.3%.
- Day-block bootstrap mean daily R 95% CI: +0.215R to +1.064R; median +0.631R/day.
- Day-block PF 95% CI: 1.453 to 5.660; P(PF >1.30)=98.9%.
- Positive/negative/zero sessions: 31 / 24 / 5.
- Top winner share of positive R: 2.5%; top five: 12.5%.

Interpretation: strongest current long candidate. Bootstrap lower PF bound is just under the formal 1.30 target at trade level, but daily resampling is comfortably above. Exact 2x-cost replay and untouched August validation remain required before promotion.

## FAILED_HOD_BREAK_30_50_MIDDAY

- n=97 / 60 sessions = 1.62 trades/day.
- PF 1.72; expectancy +0.373R; win rate 49.5%; max drawdown 6.83R.
- Development: n=70, PF 1.61, expectancy +0.326R.
- Validation: n=11, PF 2.91, expectancy +0.743R.
- Holdout: n=16, PF 1.61, expectancy +0.321R.
- Trade-bootstrap expectancy 95% CI: +0.082R to +0.665R; median +0.374R.
- Trade-bootstrap PF 95% CI: 1.132 to 2.610; median 1.728.
- Bootstrap P(PF > 1.30): 91.1%.
- Day-block bootstrap mean daily R 95% CI: +0.160R to +1.060R; median +0.600R/day.
- Day-block PF 95% CI: 1.337 to 6.561; P(PF >1.30)=97.8%.
- Positive/negative/zero sessions: 27 / 18 / 15.
- Top winner share of positive R: 2.3%; top five: 11.5%.

Interpretation: promising short candidate with materially less data than SSR. Validation and holdout are positive, but historical short borrow/locate availability and costs remain unverified, so this remains research-only.

## Promotion discipline

- No final-August data used.
- No new filters added after freezing.
- No full-day future information used in filtering.
- Exact 2x-cost minute replay still required.
- Untouched 2026-08-12 through 2026-08-27 final validation still required.
- Short strategy requires point-in-time borrow/locate feasibility before any live approval.
