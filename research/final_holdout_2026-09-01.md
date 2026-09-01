# Frozen Final Holdout — 2026-09-01

One-shot final evaluation of rules frozen before opening the 12-session SIP block from 2026-08-12 through 2026-08-27. No strategy parameter was tuned against this block.

Execution model: next-minute entry; normal 20 bps per side and stress 40 bps per side applied to both entry and exit. Corrected rescore coverage was 96/96 expected replays with zero missing windows.

| Strategy | Side | Rule | n | Trades/day | R PF | Exp R | Win | Max DD R | 2x R PF | 2x Exp R | Decision |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Extreme Pop-and-Drop | SHORT | entry >=75% vs prior close; 15% stop; 60m; 3R | 22 | 1.83 | 3.10 | +0.652 | 68.2% | 2.35 | 2.81 | +0.564 | FINAL EDGE CONFIRMED — BORROW UNVERIFIED |
| Failed HOD Break | SHORT | +30–50% midday; 5% stop; 10m; 2R | 11 | 0.92 | 1.59 | +0.373 | 63.6% | 3.50 | 1.33 | +0.195 | FINAL EDGE CONFIRMED — BORROW UNVERIFIED |
| SSR Flush Reclaim | LONG | structural risk 3–5%; 20% emergency stop; 90m; 3R | 15 | 1.25 | 1.13 | +0.047 | 40.0% | 3.23 | 0.92 | -0.033 | FINAL HOLDOUT FAIL |

Return-space PFs at normal / stress were: Pop-and-Drop 2.67 / 2.42; Failed HOD 2.75 / 2.33; SSR Reclaim 1.18 / 0.95.

Combined two-short final holdout, equal structural-R risk: n=33, 2.75 trades/day, R PF 2.34, expectancy +0.559R, win rate 66.7%, max drawdown 3.91R. At true 2x costs: R PF 2.08, expectancy +0.441R.

## Concentration

Pop-and-Drop produced 22 trades across 21 unique tickers and 10 active sessions; 8 of those active sessions were net positive. The largest single winning ticker represented ~14.1% of gross positive R. Failed HOD produced 11 trades across 10 unique tickers and 9 active sessions; 5 active sessions were net positive; the largest winning ticker represented ~17.9% of gross positive R. The Failed HOD final sample is therefore materially smaller and should be treated as the more fragile of the two passing short models.

## Causal-universe audit

The broad historical minute-download universe used whole-day H/L/V only as a permissive retrieval superset, not as an entry condition. For the three frozen strategies, inclusion is nevertheless guaranteed by information observable before each signal:

- SSR Flush Reclaim requires an RTH low <=90% of prior close before its later reclaim signal, so the -10% coarse condition was already true before entry.
- Failed HOD Break requires a prior intraday high >=125% of prior close before the failed breakout signal, so the +5% coarse condition was already true before entry.
- Pop-and-Drop requires gain_all >=30% before the breakdown signal, so the +5% coarse condition was already true before entry.

Thus the selected frozen signals do not depend on a later end-of-day move to enter the downloaded universe. A live scanner should still implement these conditions directly from running intraday state rather than daily H/L.

## Remaining execution gate

Short results remain research-only for execution until point-in-time borrow/locate feasibility is handled. Current broker metadata can be used as a live hard gate: easy-to-borrow names may be scanner-eligible, shortable-but-not-ETB names require a locate/manual path, and non-shortable names must be rejected. Current metadata is not a substitute for historical point-in-time borrow validation.

SSR Reclaim is demoted after the failed untouched holdout and must not be retuned on this final block.
