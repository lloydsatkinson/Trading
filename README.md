# Trading Research Lab

Automated research and validation platform for US small-cap momentum strategies.

Primary objectives:
- discover repeatable long-side small-cap edges;
- maximise robust profit factor and expectancy without sacrificing trade frequency;
- use chronological no-lookahead validation;
- keep prospective holdout data separate from tuned research;
- never commit credentials or broker/API secrets.

This repository is for research and paper/backtest validation. It does not auto-route live orders.

## SerClick / Leo remote research

The first production research module studies the SerClickAlot short-trap/liquidity-squeeze framework with Leo's participation filters upstream.

Locked Leo gates:
- Premarket: PM high / prior close > 1.20 and PM dollar turnover > $10m.
- 10:00: HOD through 09:59 / prior close > 1.20 and 09:30-09:59 dollar turnover > $5m.

The engine then observes shorts-building, absorption, pain-level proximity and expansion before recording ignition. Entries in the event study use the next executable one-minute bar with 25 bps slippage.

Current research priority:
- 09:30-10:30: observe trap construction; do not treat the first ignition as preferred execution.
- 10:30-15:00: prioritise LEO BOTH research signals.
- 16:00-20:00: test LEO BOTH after-hours squeezes separately.

See `docs/research/serclick_baseline_2026-08-27.md` for the locked 60-session baseline.

## Remote GitHub Actions

`SerClick Daily Research` runs after US extended hours and creates a compact latest shortlist/news artifact.

`SerClick 60D Research` runs weekly and can also be started manually. It performs the full scanner study plus conservative minute-by-minute stop/target replay.

One-time GitHub setup is required. In **Settings -> Secrets and variables -> Actions**, add these repository secrets:

- `APCA_API_KEY_ID`
- `APCA_API_SECRET_KEY`

The workflows default to `https://paper-api.alpaca.markets` for calendar/assets and use Alpaca SIP for historical market data. Never put keys in source files, issues, workflow YAML, or chat messages.

## Local verification

```bash
pip install -r requirements.txt
PYTHONPATH=. pytest -q
python scripts/run_remote_pipeline.py --feed sip --sessions 60 --end-date 2026-08-27
```

Research artifacts are written under `data/research/serclick_alpaca/<run_id>/`; compact latest outputs are mirrored to `data/latest/`. Both are ignored by git.
