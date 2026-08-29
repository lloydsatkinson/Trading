# Fixed 50% Stop Replay — 2026-08-29

Source: frozen candidates from the completed 60-session SIP minute tournament (2026-05-15 through 2026-08-11). Final 2026-08-12 through 2026-08-27 block remains untouched.

Policy tested: preserve the original strategy entry and original profit target; replace only the stop with a fixed 50% adverse move from entry. Normal modeled exit slippage = 20 bps. $1,000 examples below assume $1,000 notional per trade, so a full 50% stop is approximately a $500 planned loss before gap/slippage.

Coverage: 233 / 233 frozen trades replayed; 0 missing.

## Results

### FAILED_HOD_BREAK_30_50_MIDDAY — SHORT
- n=97 / 60 sessions = 1.62 trades/day.
- Fixed-50% PF: 1.617.
- Average return/trade: +1.969% = +$19.69 on $1,000 notional.
- Win rate: 76.29%.
- Total simple P&L across the 97 historical $1,000-notional trades: +$1,910.36.
- Average across all 60 sessions: +$31.84/day.
- 61 target exits, 33 time exits, 3 full 50% stops.
- Worst individual return: -50.30%; best +19.82%.
- Split PF: development 1.589; validation 1.271; holdout 2.063.
- Important: short results remain theoretical until point-in-time borrow/locate availability and fees are joined.

Original structural-stop comparison on the same candidates (raw return basis): PF 1.484, +1.117% average/trade, 49.48% wins. The 50% stop therefore improved PF, average return and win rate in this specific replay, at the cost of much larger tail loss when a wide stop is actually hit.

### SSR_FLUSH_RECLAIM_RISK_3_5 — LONG
- n=136 / 60 sessions = 2.27 trades/day.
- Fixed-50% PF: 1.627.
- Average return/trade: +0.673% = +$6.73 on $1,000 notional.
- Win rate: 56.62%.
- Total simple P&L across the 136 historical $1,000-notional trades: +$915.82.
- Average across all 60 sessions: +$15.26/day.
- 16 target exits, 120 time exits, 0 full 50% stops.
- Worst individual return: -12.16%; best +9.69%.
- Split PF: development 1.125; validation 1.813; holdout 4.305.

Original structural-stop comparison on the same candidates (raw return basis): PF 1.856, +1.081% average/trade, 55.15% wins. The 50% stop reduced overall PF and average return, despite a slightly higher win rate. Structural risk control remains preferred for this long candidate until further evidence.

## Combined $1,000-notional illustration
Taking every qualifying frozen trade with $1,000 notional each, no compounding:
- Historical total across 60 sessions: +$2,826.18.
- Average: +$47.10/session.
- 40 positive sessions, 19 negative, 1 flat.
- Best session: +$376.37.
- Worst session: -$364.16.

These are historical research results, not a profit forecast. Fixed 50% stop is now a controllable replay parameter rather than a hard-coded strategy assumption.
