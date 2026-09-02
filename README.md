# Trading Research Lab

Automated research and validation platform for US micro-cap and small-cap momentum strategies.

Primary objectives:
- discover repeatable long- and short-side intraday and short-horizon swing edges;
- maximise robust profit factor and expectancy without sacrificing useful trade frequency;
- use chronological no-lookahead validation;
- keep locked-test and prospective-forward data separate from tuned research;
- model next-bar execution, adverse slippage, session boundaries, overnight gaps and incomplete swing horizons;
- never commit credentials or broker/API secrets.

This repository is for research and paper/backtest validation. It does not auto-route live orders.

## Multi-strategy microcap research

The shared research framework compares four mechanically defined signal families:

1. **Stocks-in-Play 5-minute ORB** — direct breakout, breakout/pullback long, negative-gap short and failed-gap reversal short.
2. **High-RVOL VWAP Momentum/Reclaim** — post-impulse VWAP reclaim long and failed-reclaim/rejection short.
3. **SerClick / Leo** — the existing short-trap/absorption/expansion signal, preserved behind a compatibility adapter.
4. **Dan Irish secondary-move research** — catalyst/activity-driven continuation research covering intraday consolidation breakouts plus Dan-inspired overnight, Day-2 and multi-day continuation variants.

Dan swing variants are deliberately labelled **Dan-inspired** rather than presented as an exact reproduction of any trader's private rules. Publicly observable ideas are converted into mechanical hypotheses and tested under the same validation discipline as the other strategies.

Primary known-cap research buckets are:
- Micro-cap: **$50M-$300M**.
- Small-cap: **$300M-$2B**.

Historical market-cap values are never backfilled from future snapshots. If a contemporaneous cap is unavailable, the observation remains `UNKNOWN` and is reported separately.

ORB/VWAP discovery retains its original **$1-$30** price gate. Dan research is segmented separately across price buckets from **below $1 through $100+** so the new family cannot silently broaden the existing ORB/VWAP universe.

### Shared execution research

Intraday strategy families use conservative replay assumptions:
- signal candle must complete before entry;
- entry uses the next executable one-minute bar;
- adverse entry-slippage scenarios: **10, 25, 50, 75 and 100 bps**;
- same-minute stop/target ambiguity is resolved stop-first;
- percentage stops plus strategy structural stops;
- fixed percentage targets plus **1R, 1.5R, 2R, 3R and 4R** structural targets;
- intraday hold windows: **5, 10, 15, 30, 45, 60, 90, 120, 180 and 240 minutes**, plus EOD;
- exact maximum-profit / time-to-peak analysis;
- ORB/VWAP/Dan intraday trades are capped at the **16:00 ET** regular-session boundary;
- SerClick research is capped before **20:00 ET**.

Dan swing replay adds:
- **1, 2, 3, 4, 5, 7 and 10-session** hold horizons;
- percentage stops of **5%, 8%, 10%, 15% and 20%** plus the signal's structural stop reference;
- percentage targets of **5%, 10%, 15%, 20%, 30%, 40% and 50%** plus **1R, 1.5R, 2R, 3R and 4R** targets;
- gap-through-stop handling using the first available opening price rather than an impossible fill at the stop;
- conservative target fills at the configured target level;
- explicit right-censor and split-boundary censor flags.

A swing replay is excluded from rule-selection metrics whenever its requested future horizon crosses a development/validation/test boundary or extends beyond the available historical data.

### Validation labels

- `development`: hypothesis formation only.
- `validation`: parameter/rule selection.
- `test`: locked historical evaluation; never used to choose a rule.
- `forward`: prospective observations; never used to choose or retune a rule.

The cross-strategy leaderboard is selected from **25-bps validation results only**, with explicit sample-size, drawdown and slippage-resilience components. Forward performance can be displayed beside the selected rule but cannot improve its selection score.

The current production flag requires at least the normal sample gate and **5% validation expectancy** at the baseline execution assumption. Failing the production flag does not remove a research row; it remains visible for diagnosis and further evidence gathering.

Dan parameter combinations also preserve `setup_id` through reporting and ranking so different qualification thresholds cannot be pooled into one apparently stronger result.

Run Dan only:

```bash
python scripts/run_strategy_research.py --strategy dan --feed sip --sessions 60
```

Run the unified study:

```bash
python scripts/run_strategy_research.py --strategy all --feed sip --sessions 60
```

A 60-session run is useful for engineering verification and initial research. It is **not sufficient promotion evidence for 1-10 day swing rules**; longer independent history and prospective forward observations are required before treating a swing configuration as validated.

Outputs are written to `data/research/multistrategy/<run_id>/` and compact results are mirrored into `data/latest/`:
- `signals.csv`
- `replay_grid.csv.gz`
- `strategy_summary.csv`
- `market_cap_summary.csv`
- `leaderboard.csv`
- `slippage_summary.csv`
- `peak_timing.csv`
- `best_hold_times.csv`
- `price_bucket_summary.csv`
- `retained_gain_summary.csv`
- `swing_hold_summary.csv`
- `overnight_gap_risk.csv`
- `censor_summary.csv`
- `news.md`

See `docs/research/multistrategy_methodology.md` for the research protocol.

## SerClick / Leo locked baseline

The original production research module studies the SerClickAlot short-trap/liquidity-squeeze framework with Leo's participation filters upstream.

Locked Leo gates:
- Premarket: PM high / prior close > 1.20 and PM dollar turnover > $10m.
- 10:00: HOD through 09:59 / prior close > 1.20 and 09:30-09:59 dollar turnover > $5m.

Current research priority:
- 09:30-10:30: observe trap construction; do not treat the first ignition as preferred execution.
- 10:30-15:00: prioritise LEO BOTH research signals.
- 16:00-20:00: test LEO BOTH after-hours squeezes separately.

The already-inspected 60-session SerClick historical block is frozen through **2026-08-27**. New SerClick sessions from **2026-08-28 onward** are treated as prospective `forward` observations by the unified runner.

See `docs/research/serclick_baseline_2026-08-27.md` for the locked baseline.

## Remote GitHub Actions

`SerClick Daily Research` runs after US extended hours and creates a compact latest shortlist/news artifact.

`SerClick 60D Research` runs weekly and can also be started manually. It performs the full scanner study plus conservative minute-by-minute replay.

One-time GitHub setup is required. In **Settings -> Secrets and variables -> Actions**, add these repository secrets:

- `APCA_API_KEY_ID`
- `APCA_API_SECRET_KEY`

The workflows default to `https://paper-api.alpaca.markets` for calendar/assets and use Alpaca SIP for historical market data. Never put keys in source files, issues, workflow YAML, or chat messages.

## Local verification

```bash
pip install -r requirements.txt
PYTHONPATH=. pytest -q
python -m compileall -q scanner scripts
```

The unit/compile CI is API-free. Market-data research jobs are separate from CI.
