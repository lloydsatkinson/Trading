# US Small-Cap Runner Research

## Objective

Find repeatable long-side US small-cap strategies with a useful number of trades and a high, cost-adjusted profit factor. Historical PF alone is not sufficient: strategies must survive chronological validation and a frozen later regime.

## Research principles

- Signal-time features only; future returns are outcome labels only.
- Chronological development, validation, holdout and final-regime splits.
- Rank candidates without looking at the final split.
- Apply realistic round-trip cost stress before ranking.
- Require sample size and trade-frequency reporting alongside PF.
- Reject strategies that collapse in a later regime instead of retuning them on that regime.
- No live order routing from this research package.

## Strategy families

1. Catalyst Early Runner — modest initial move, moderate abnormal volume and a fresh SEC event; seek the next-session continuation before the stock becomes extremely extended.
2. SBE / Secondary Expansion — initial impulse, retained gain, contraction and renewed volume through a pivot.
3. DIM — Dan Irish-style secondary move: catalyst/volume, initial expansion, price retention, tight base and quick re-expansion.
4. Absorption Reclaim — heavy selling ceases to produce downside; reclaim of VWAP/pain levels signals renewed demand.
5. Former Runner — Day 2–5 runner stabilises after a fade and re-expands.

The tournament keeps these concepts independent so that one attractive historical feature set does not silently contaminate every strategy.
