# Hold-Time Sweep — 2026-08-29

Frozen candidates only. Stop fixed at 50%. Original entry and profit target preserved. Holds tested: 5, 10, 15, 20, 30, 45, 60, 90, 120, 180, 300 minutes. Selection uses development first; validation and holdout are reporting/stability checks. Final 2026-08-12 through 2026-08-27 block remains untouched.

Implementation note: the completed sweep was serialized into one SIP market-data pass to avoid concurrent API rate-limit distortion; all hold variants were replayed from the same bars. Coverage was 2,563 / 2,563 expected replays, with zero missing candidate windows.

## FAILED_HOD_BREAK_30_50_MIDDAY — SHORT

Development-only maximum dollar P&L selected **30 minutes**.

- 30m overall: n=97, PF **1.623**, win rate **72.2%**, avg **+$19.68 per $1,000 trade**, total **+$1,909.31** over the 60-session research period.
- Development: PF **1.685**, +$18.67/trade.
- Validation: PF **1.312**, +$15.07/trade.
- Holdout: PF **1.699**, +$27.30/trade.
- Exit mix at 30m: 60 target, 34 time, 3 stop.

Raw all-sample dollar P&L peaks at 60m (+$1,933.87), only ~$24.56 more than 30m over 60 sessions, while development performance is weaker (PF 1.453 vs 1.685) and exposure doubles. Therefore **30m is the frozen research hold** for the final unseen test.

## SSR_FLUSH_RECLAIM_RISK_3_5 — LONG

Development-only maximum dollar P&L was **180 minutes**, but this fails the stability gate: holdout PF **0.941** and -$1.53/trade. Therefore 180m is rejected.

The strongest stable-looking plateau is **60–90 minutes**, with **90 minutes** the frozen candidate for the final unseen test:

- 90m overall: n=136, PF **2.215**, win rate **58.1%**, avg **+$13.48 per $1,000 trade**, total **+$1,832.99**.
- Development: PF **1.669**, +$8.01/trade.
- Validation: PF **3.228**, +$24.28/trade.
- Holdout: PF **2.670**, +$14.70/trade.
- Exit mix at 90m: 27 target, 109 time, 0 full 50% stops.

Because 90m was identified after inspecting stability across the existing splits, it is **not promoted from these data**. It is frozen now and must prove itself on the untouched 2026-08-12 through 2026-08-27 final block.

## Combined research economics at frozen holds

Using $1,000 notional per qualifying trade, fixed 50% stop, original targets, 20bp modeled exit slippage:

- Failed HOD 30m: +$1,909.31 over 60 sessions (~+$31.82/session).
- SSR Reclaim 90m: +$1,832.99 over 60 sessions (~+$30.55/session).
- Combined: **+$3,742.30** over 60 sessions (~**+$62.37/session**), before historical short borrow/locate fees and without assuming scalability.

These are research backtest results, not profit forecasts. Short borrow/locate availability and halt/gap-through-stop risk remain execution constraints.
