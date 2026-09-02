from __future__ import annotations

import json
from pathlib import Path
from time import perf_counter

import pandas as pd

from scanner.multistrategy.study import MultiStrategyStudy
from scanner.strategies.dan_irish.research import (
    generate_dan_signal_set,
    make_cached_symbol_minute_loader,
    replay_dan_swing_signals,
)
from scripts.run_strategy_research import _load_minute_bars


ROOT = Path(".")
FEED = "sip"
SESSIONS = 10
END_DATE = "2026-08-31"
SAMPLE_SWING_SIGNALS = 5


def seconds(start: float) -> float:
    return round(perf_counter() - start, 3)


def announce(label: str, **values) -> None:
    payload = " ".join(f"{key}={value}" for key, value in values.items())
    print(f"BENCHMARK_STAGE {label} {payload}".rstrip(), flush=True)


def main() -> None:
    output = ROOT / "data" / "benchmark" / "dan-runtime"
    output.mkdir(parents=True, exist_ok=True)

    total_start = perf_counter()
    study = MultiStrategyStudy(root=ROOT, feed=FEED, sessions=SESSIONS, end_date=END_DATE)

    announce("discovery_start", sessions=SESSIONS, end_date=END_DATE)
    start = perf_counter()
    meta = study.run(include_dan_candidates=True)
    discovery_seconds = seconds(start)
    contexts = meta.get("dan_candidate_contexts", pd.DataFrame())
    announce(
        "discovery_done",
        seconds=discovery_seconds,
        candidates=len(contexts),
        symbols=(contexts["symbol"].nunique() if not contexts.empty and "symbol" in contexts.columns else 0),
    )

    cached_loader = make_cached_symbol_minute_loader(_load_minute_bars, max_days=24)
    announce("signal_generation_start")
    start = perf_counter()
    signals, signal_skips = generate_dan_signal_set(
        ROOT,
        FEED,
        study,
        meta,
        cached_loader,
    )
    signal_generation_seconds = seconds(start)

    if signals.empty or "_replay_mode" not in signals.columns:
        swing_signals = pd.DataFrame()
        intraday_signals = pd.DataFrame()
    else:
        modes = signals["_replay_mode"].fillna("intraday").astype(str)
        swing_signals = signals[modes.eq("swing")].copy()
        intraday_signals = signals[modes.eq("intraday")].copy()
    announce(
        "signal_generation_done",
        seconds=signal_generation_seconds,
        signals=len(signals),
        intraday=len(intraday_signals),
        swing=len(swing_signals),
        skips=len(signal_skips),
    )

    sort_cols = [c for c in ("date", "symbol", "variant_id", "setup_id", "entry_timestamp") if c in swing_signals.columns]
    sample = swing_signals.sort_values(sort_cols).head(SAMPLE_SWING_SIGNALS).copy() if not swing_signals.empty else pd.DataFrame()

    announce("swing_replay_start", sample_signals=len(sample), slippage_bps=25)
    start = perf_counter()
    if sample.empty:
        sample_replays = pd.DataFrame()
        sample_skips = pd.DataFrame()
    else:
        sample_replays, sample_skips = replay_dan_swing_signals(
            ROOT,
            FEED,
            sample,
            meta.get("daily_bars", pd.DataFrame()),
            meta.get("split_end_dates", {}),
            cached_loader,
            slippage_bps=(25.0,),
        )
    sample_replay_seconds = seconds(start)

    replay_rows = int(len(sample_replays))
    announce(
        "swing_replay_done",
        seconds=sample_replay_seconds,
        replay_rows=replay_rows,
        rows_per_second=(round(replay_rows / sample_replay_seconds, 3) if sample_replay_seconds > 0 else None),
    )

    benchmark = {
        "feed": FEED.upper(),
        "sessions": SESSIONS,
        "end_date": END_DATE,
        "study_start_date": str(meta.get("start_date")),
        "study_end_date": str(meta.get("end_date")),
        "candidate_rows": int(len(contexts)),
        "candidate_symbols": int(contexts["symbol"].nunique()) if not contexts.empty and "symbol" in contexts.columns else 0,
        "signal_rows": int(len(signals)),
        "intraday_signal_rows": int(len(intraday_signals)),
        "swing_signal_rows": int(len(swing_signals)),
        "signal_skip_rows": int(len(signal_skips)),
        "sample_swing_signals": int(len(sample)),
        "sample_swing_replay_rows": replay_rows,
        "sample_swing_skip_rows": int(len(sample_skips)),
        "discovery_seconds": discovery_seconds,
        "signal_generation_seconds": signal_generation_seconds,
        "sample_swing_replay_seconds": sample_replay_seconds,
        "sample_replay_rows_per_second": round(replay_rows / sample_replay_seconds, 3) if sample_replay_seconds > 0 else None,
        "sample_replay_rows_per_signal": round(replay_rows / len(sample), 3) if len(sample) else None,
        "total_seconds": seconds(total_start),
    }

    (output / "benchmark.json").write_text(json.dumps(benchmark, indent=2), encoding="utf-8")
    contexts.to_csv(output / "candidate_contexts.csv.gz", index=False, compression="gzip")
    signals.to_csv(output / "signals.csv.gz", index=False, compression="gzip")
    sample.to_csv(output / "sample_swing_signals.csv", index=False)
    sample_replays.to_csv(output / "sample_swing_replays.csv.gz", index=False, compression="gzip")
    signal_skips.to_csv(output / "signal_skips.csv", index=False)
    sample_skips.to_csv(output / "sample_replay_skips.csv", index=False)

    print(json.dumps(benchmark, indent=2), flush=True)


if __name__ == "__main__":
    main()
