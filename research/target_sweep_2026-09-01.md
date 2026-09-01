# Structural-R Target Sweep — 2026-09-01

Frozen pre-final-holdout configurations only. Targets tested at 0.5R, 1R, 1.5R, 2R, 2.5R, 3R, 4R and 5R, where R is original chart-structural risk. Final 2026-08-12 through 2026-08-27 remained untouched during this work.

## Frozen rules for the one-shot final holdout

### SSR Flush Reclaim — balanced long
- Filter: SSR_FLUSH_RECLAIM with original structural risk >=3% and <5%.
- Emergency stop: 20% from entry.
- Maximum hold: 90 minutes.
- Profit target: 3R of original chart-structural risk.
- 60-session research result: n=136 (~2.27/day), return PF 2.938, R-PF 3.042, expectancy +0.461R, win rate 60.3%, avg return +1.873% (+$18.73 per $1,000 notional).
- Split target-3R PF: development 2.631, validation 3.536, internal holdout 3.019.

### Failed HOD Break — risk-efficient short
- Filter: FAILED_HOD_BREAK, 10:30–13:00 ET, entry 30–50% above previous close, original structural risk <10%.
- Fixed stop: 5% from entry.
- Maximum hold: 10 minutes.
- Profit target: 2R of original chart-structural risk.
- 60-session research result: n=97 (~1.62/day), return PF 1.751, R-PF 1.675, expectancy +0.353R, win rate 54.6%, avg return +1.498% (+$14.98 per $1,000 notional).
- Split target-2R PF: development 1.617, validation 3.939, internal holdout 1.413.
- The prior 50%/30m aggressive variant remains a sensitivity study only; it is not the promotion configuration because of much larger drawdown/tail risk.

### Extreme Pop-and-Drop — balanced short
- Filter: POP_AND_DROP with entry still >=75% above previous close.
- Fixed stop: 15% from entry.
- Maximum hold: 60 minutes.
- Profit target: 3R of original chart-structural risk.
- 60-session research result: n=122 (~2.03/day), return PF 2.474, R-PF 2.413, expectancy +0.591R, win rate 71.3%, avg return +5.671% (+$56.71 per $1,000 notional).
- Split target-3R PF: development 2.847, validation 2.516, internal holdout 1.682.

## Selection discipline

SSR used 3R rather than the 5R in-sample maximum because 3R–5R forms a strong plateau and 3R is less boundary-seeking. Pop-and-Drop uses the development-selected 3R target, with 2R–5R also positive across validation/holdout. Failed-HOD uses 2R because the aggressive configuration deteriorated above 2R in validation and the 5% risk-efficient version showed a broad 1.5R–4R positive plateau.

These rules are now frozen before the final 2026-08-12 through 2026-08-27 test. Short strategies remain research-only until point-in-time borrow/locate availability, fees, SSR restrictions and halt/gap-through-stop execution are modeled.
