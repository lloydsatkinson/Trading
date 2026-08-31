# Dan Irish Strategy Family Plan — Self-Review Corrections

This file is a required companion to `docs/superpowers/plans/2026-08-31-dan-irish-strategy-family.md` and overrides any conflicting instruction in that plan. Executors must read the approved spec, the main implementation plan, and this correction file before code changes.

## 1. Setup identities must never be pooled

The main plan's `variant_id` values remain the four conceptual variants, but every entry-forming hypothesis must also emit a stable `setup_id`.

For intraday signals, define:

```python
def dan_intraday_setup_id(consolidation_minutes: int, breakout_reference: str, min_volume_ratio: float) -> str:
    ref = str(breakout_reference).upper()
    ratio = str(float(min_volume_ratio)).replace(".", "P")
    return f"C{int(consolidation_minutes)}_{ref}_V{ratio}"
```

Allowed breakout references are `BASE_HIGH`, `HOD`, `PM_HIGH`. Generate separate signal attempts for consolidation durations `(10, 20, 30, 45, 60, 90)` and breakout-volume thresholds `(1.0, 1.5, 2.0)` when the required reference exists. A setup that yields the same timestamp as another setup still retains a distinct `setup_id` because it is a separate hypothesis.

For swing signals, `setup_id` must encode the entry family and structure that changes entry timing:

```python
def dan_swing_setup_id(entry_family: str, base_length_sessions: int | None = None, breakout_reference: str | None = None) -> str:
    parts = [str(entry_family).upper()]
    if base_length_sessions is not None:
        parts.append(f"B{int(base_length_sessions)}")
    if breakout_reference:
        parts.append(str(breakout_reference).upper())
    return "_".join(parts)
```

Replay identity must combine setup and exit rule before reporting/ranking:

```python
replay["exit_rule_id"] = replay["rule_id"]
replay["rule_id"] = replay["setup_id"].astype(str) + "__" + replay["exit_rule_id"].astype(str)
```

Add tests:

```python
def test_two_entry_setups_are_not_pooled_under_one_rule_id():
    rows = pd.DataFrame([
        {"setup_id": "C10_BASE_HIGH_V1P0", "rule_id": "S05_T10_H60"},
        {"setup_id": "C30_BASE_HIGH_V1P0", "rule_id": "S05_T10_H60"},
    ])
    rows["exit_rule_id"] = rows["rule_id"]
    rows["rule_id"] = rows["setup_id"] + "__" + rows["exit_rule_id"]
    assert rows["rule_id"].nunique() == 2
```

Continuous thresholds that do not change entry timing — impulse %, dollar turnover, retained-gain ratio and observed pullback depth — are retained as numeric features and analysed by threshold-grid summaries rather than creating duplicate identical trades. Add `summarize_dan_threshold_grid(replays)` that evaluates the approved grids using only rows whose continuous features satisfy each cut; threshold-summary identity must include the cut values so results are auditable.

## 2. Retained-gain checkpoints are explicit analysis fields

Add to `scanner/strategies/dan_irish/features.py`:

```python
def retained_gain_checkpoint_values(
    bars: pd.DataFrame,
    impulse_timestamp,
    impulse_start_price: float,
    impulse_high_price: float,
) -> dict[str, float]:
    x = prepare_intraday_bars(bars)
    impulse_ts = pd.Timestamp(impulse_timestamp)
    if impulse_ts.tzinfo is None:
        impulse_ts = impulse_ts.tz_localize("America/New_York")
    else:
        impulse_ts = impulse_ts.tz_convert("America/New_York")
    out = {}
    for minutes in (10, 20, 30, 60, 90):
        cutoff = impulse_ts + pd.Timedelta(minutes=minutes)
        eligible = x[x["timestamp_et"] <= cutoff]
        ref = float(eligible.iloc[-1]["close"]) if not eligible.empty else np.nan
        out[f"retained_gain_{minutes}m"] = retained_gain_ratio(impulse_start_price, impulse_high_price, ref)
    return out
```

Regular close, after-hours reference, next open, Day-2 close and Day-3 close are calculated only after those timestamps exist and are reporting/outcome features. They must never be added back into a signal's qualification input for an earlier entry.

Required columns where data exists:

- `retained_gain_10m`
- `retained_gain_20m`
- `retained_gain_30m`
- `retained_gain_60m`
- `retained_gain_90m`
- `retained_gain_close`
- `retained_gain_afterhours`
- `retained_gain_next_open`
- `retained_gain_day2_close`
- `retained_gain_day3_close`

Add an anti-lookahead test by altering bars after the requested checkpoint and asserting the earlier checkpoint is unchanged.

## 3. Swing replay must include the approved structural/dynamic exits

Extend the `SwingReplayRule` in the main plan to these fields:

```python
@dataclass(frozen=True)
class SwingReplayRule:
    stop_mode: str = "PCT"
    stop_pct: float | None = None
    stop_price: float | None = None
    atr_multiple: float | None = None
    target_pct: float | None = None
    target_r_multiple: float | None = None
    trailing_exit: str | None = None
    max_hold_sessions: int = 1
```

Supported `stop_mode` values:

- `PCT`
- `STRUCTURAL_BASE`
- `PRIOR_DAY_LOW`
- `DAY0_SUPPORT`
- `ATR`
- `ANCHORED_VWAP`

Supported `trailing_exit` values:

- `NONE`
- `PRIOR_DAY_LOW_BREAK`
- `BASE_FAILURE`
- `ANCHORED_VWAP_LOSS`
- `TRAILING_HIGHER_LOW`

Rules may combine one initial stop mode, one optional target, one optional trailing exit and one maximum hold.

Dynamic levels must use completed information only. For example, a prior-day-low stop used on Tuesday is Monday's completed low; Tuesday's eventual low cannot set Tuesday's stop. A trailing higher-low may update only after the relevant prior session is complete.

ATR-normalised stop uses an ATR value calculated only from completed daily sessions before entry:

```python
stop = entry_price - atr_multiple * pre_entry_atr
```

for long trades.

Anchored VWAP is anchored at Day-0 ignition and uses only bars through the current replay timestamp. It may be computed from minute volume and provider VWAP/typical price using the existing volume-weighted convention.

Add tests:

```python
def test_prior_day_low_stop_does_not_use_current_day_future_low():
    result_a = simulate_multisession_trade(bars_without_late_crash(), ..., rule=SwingReplayRule(stop_mode="PRIOR_DAY_LOW", max_hold_sessions=2))
    result_b = simulate_multisession_trade(bars_with_late_crash_after_exit_window(), ..., rule=SwingReplayRule(stop_mode="PRIOR_DAY_LOW", max_hold_sessions=2))
    assert result_a.exit_timestamp == result_b.exit_timestamp


def test_anchored_vwap_loss_uses_only_vwap_known_at_exit_bar():
    result = simulate_multisession_trade(avwap_loss_fixture(), ..., rule=SwingReplayRule(stop_mode="STRUCTURAL_BASE", trailing_exit="ANCHORED_VWAP_LOSS", max_hold_sessions=3))
    assert result.exit_reason == "ANCHORED_VWAP_LOSS"
```

The default swing rule builder must include percentage controls, structural base stop, prior-day-low stop, Day-0 support stop, ATR stop and anchored-VWAP stop where required signal inputs are available. Do not silently create a rule when its required level cannot be calculated.

## 4. Price/volume research grid outputs must be auditable

Add `dan_threshold_summary.csv` to the runner outputs. It evaluates the approved continuous cut grids:

- impulse: 15%, 20%, 30%, 50%, 75%
- dollar turnover: $1M, $3M, $5M, $10M
- retained gain: 40%, 50%, 65%, 80%
- maximum pullback depth: 10%, 20%, 30%, 40%, 50%

For each cut combination, report at minimum:

- `strategy_id`
- `variant_id`
- `setup_id`
- `rule_id`
- `split`
- `slippage_bps`
- threshold columns
- `n`
- `win_rate`
- `expectancy`
- `profit_factor`
- `mean_r`
- `max_drawdown`

Only validation rows may be used to select a threshold combination. Test and forward columns are joined after selection exactly like the current ranking approach.

## 5. Explicit Alpaca adjustment mode and corporate-action auditability

The current Alpaca client already supports `adjustment` and defaults to `raw`. Preserve that default for compatibility, but make the research choice explicit.

Add to `MultiStrategyConfig`:

```python
bar_adjustment: str = "raw"
```

All Dan-relevant `stock_bars()` calls pass:

```python
adjustment=self.cfg.bar_adjustment
```

and the runner writes:

```python
meta["bar_adjustment"] = study.cfg.bar_adjustment
```

Add a test that a fake Alpaca API receives `adjustment="raw"` for the Dan daily/minute fetch path.

If a split/corporate action causes a discontinuity that cannot be reconciled under the chosen adjustment mode, mark the swing candidate/replay `corporate_action_flag=true` and exclude it from production-selection summaries until reviewed. Do not repair historical returns by applying current shares or market-cap information backward.

## 6. Correct production-gate regression test

Do not use the existing `_row()` helper's `rule` argument as if it were a variant. The Dan production-gate test should construct the row explicitly:

```python
def test_dan_swing_still_uses_existing_ten_percent_production_hurdle():
    summary = pd.DataFrame([{
        "strategy_id": "DAN_IRISH",
        "variant_id": "DAN_DAY2_CONTINUATION",
        "direction": "LONG",
        "rule_id": "DAY2_BASE_HIGH__S08_T20_HS3",
        "split": "validation",
        "slippage_bps": 25,
        "n": 30,
        "profit_factor": 1.8,
        "expectancy": 0.09,
        "median_return": 0.02,
        "max_drawdown": -0.15,
    }])
    ranked = rank_strategies(summary, min_n=20)
    assert bool(ranked.iloc[0]["production_eligible"]) is False
```

## 7. Completion checks added by self-review

Before implementation is described as complete, the full verification must additionally prove:

```bash
PYTHONPATH=. pytest tests/test_dan_features.py tests/test_dan_intraday.py tests/test_dan_swing_signals.py tests/test_multisession_replay.py tests/test_dan_reporting.py tests/test_dan_runner_integration.py tests/test_dan_regressions.py -q
PYTHONPATH=. pytest -q
python -m compileall -q scanner scripts
```

And inspect the generated synthetic/API-free artifacts to confirm:

- `rule_id` includes `setup_id` and does not pool entry hypotheses;
- censored swing rows are excluded from selection metrics;
- `dan_threshold_summary.csv` exists;
- all eight price buckets can be represented;
- `bar_adjustment` is present in run metadata;
- existing ORB/VWAP candidate defaults remain $1-$30;
- SerClick historical lock remains 2026-08-27;
- the 10% production expectancy hurdle remains unchanged.
