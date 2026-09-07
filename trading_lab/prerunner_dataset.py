from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
import json
from pathlib import Path
from typing import Sequence

import pandas as pd

from .alpaca_intraday import chunks, common_assets, et
from .prerunner import build_snapshots
from .prerunner_pipeline import assemble_labeled_snapshots
from .prerunner_remote import daily_prior_context, select_signal_time_candidates


def eligible_symbol_map(
    context: dict[tuple[str, date], dict],
    sessions: Sequence[date],
    *,
    min_price: float = 0.75,
    max_price: float = 20.0,
    min_prior_volume: float = 50_000.0,
) -> dict[date, list[str]]:
    out: dict[date, list[str]] = {}
    symbols = sorted({ticker for ticker, _ in context})
    for session in sessions:
        names = []
        for ticker in symbols:
            row = context.get((ticker, session))
            if not row:
                continue
            previous_close = row.get("previous_close")
            prior_volume = row.get("prior20_median_volume")
            if previous_close is None or prior_volume is None:
                continue
            if min_price <= float(previous_close) <= max_price and float(prior_volume) >= min_prior_volume:
                names.append(ticker)
        out[session] = names
    return out


def _bar_num(row: dict, short: str, long: str) -> float:
    try:
        return float(row.get(short, row.get(long, 0.0)) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def standardize_api_bars(raw: dict[str, list[dict]], session: date, context: dict[tuple[str, date], dict]) -> pd.DataFrame:
    rows = []
    for symbol, bars in (raw or {}).items():
        ticker = str(symbol).upper()
        ctx = context.get((ticker, session), {})
        for bar in bars or []:
            timestamp = bar.get("t") or bar.get("timestamp")
            if not timestamp:
                continue
            rows.append({
                "session_date": session.isoformat(),
                "date": session.isoformat(),
                "ticker": ticker,
                "timestamp": timestamp,
                "open": _bar_num(bar, "o", "open"),
                "high": _bar_num(bar, "h", "high"),
                "low": _bar_num(bar, "l", "low"),
                "close": _bar_num(bar, "c", "close"),
                "volume": _bar_num(bar, "v", "volume"),
                "previous_close": ctx.get("previous_close"),
                "prior20_median_volume": ctx.get("prior20_median_volume"),
                "prior20_max_volume": ctx.get("prior20_max_volume"),
                "prior4d_return": ctx.get("prior4d_return"),
            })
    return pd.DataFrame(rows)


def _fetch_frame(client, symbols: Sequence[str], timeframe: str, start, end, session: date, context, batch_size: int, asof: str | None = None) -> pd.DataFrame:
    frames = []
    for batch in chunks(list(symbols), batch_size):
        raw = client.bars(batch, timeframe, start, end, asof=asof)
        frame = standardize_api_bars(raw, session, context)
        if not frame.empty:
            frames.append(frame)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _history_for(opening: pd.DataFrame, ticker: str, current_date: str, history_sessions: int) -> pd.DataFrame:
    if opening.empty:
        return opening
    h = opening[(opening["ticker"] == ticker) & (opening["session_date"] < current_date)]
    if h.empty:
        return h
    dates = sorted(h["session_date"].unique())[-history_sessions:]
    return h[h["session_date"].isin(dates)].copy()


def _attach_retrospective_diagnostics(candidates: pd.DataFrame, context: dict[tuple[str, date], dict]) -> pd.DataFrame:
    if candidates.empty:
        return candidates
    out = candidates.copy()
    up, down = [], []
    for _, row in out.iterrows():
        d = date.fromisoformat(str(row["session_date"]))
        c = context.get((str(row["ticker"]).upper(), d), {})
        prev = c.get("previous_close")
        high = c.get("high")
        low = c.get("low")
        if prev and high:
            up.append(float(high) / float(prev) - 1.0)
        else:
            up.append(float("nan"))
        if prev and low:
            down.append(1.0 - float(low) / float(prev))
        else:
            down.append(float("nan"))
    out["retrospective_day_up_pct"] = up
    out["retrospective_day_down_pct"] = down
    out["retrospective_long_20"] = out["retrospective_day_up_pct"] >= 0.20
    out["retrospective_short_20"] = out["retrospective_day_down_pct"] >= 0.20
    return out


def prepare_prerunner_dataset(
    client,
    output: str | Path,
    *,
    days: int = 60,
    end_date: date = date(2026, 8, 11),
    history_sessions: int = 14,
    max_symbols: int | None = None,
    max_active_per_day: int = 250,
    random_controls_per_day: int = 25,
    min_price: float = 0.75,
    max_price: float = 20.0,
    min_prior_volume: float = 50_000.0,
) -> dict:
    """Build the remote microcap pre-runner dataset without future-based sampling.

    The expensive full-day one-minute pull happens only after a permissive scanner
    built from data available through 09:35 ET. Same-day future H/L is attached only
    after selection for diagnostics and never participates in the gate.
    """
    out = Path(output)
    out.mkdir(parents=True, exist_ok=True)
    if days < 10:
        raise ValueError("days must be at least 10 for chronological research")

    calendar = client.calendar(end_date - timedelta(days=(days + 40) * 3), end_date)
    sessions = sorted({date.fromisoformat(str(row["date"])[:10]) for row in calendar if date.fromisoformat(str(row["date"])[:10]) <= end_date})
    needed = days + max(22, history_sessions + 2)
    if len(sessions) < needed:
        raise RuntimeError("not enough market sessions")
    eval_sessions = sessions[-days:]
    context_sessions = sessions[-needed:]

    assets = common_assets(client.assets())
    if max_symbols:
        assets = assets[:max_symbols]
    symbols = [str(a["symbol"]).upper() for a in assets]
    pd.DataFrame(assets).to_csv(out / "universe.csv", index=False)
    print(f"prerunner universe={len(symbols):,} sessions={eval_sessions[0]}..{eval_sessions[-1]} feed={client.feed}")

    daily = defaultdict(list)
    for no, batch in enumerate(chunks(symbols, 400), start=1):
        raw = client.bars(
            batch,
            "1Day",
            et(context_sessions[0], 0),
            et(eval_sessions[-1], 0) + timedelta(days=1),
            asof=end_date.isoformat(),
        )
        for ticker, bars in raw.items():
            daily[ticker].extend(bars)
        print("prerunner daily batch", no, len(batch))

    context = daily_prior_context(dict(daily), context_sessions)
    eligible = eligible_symbol_map(
        context,
        eval_sessions,
        min_price=min_price,
        max_price=max_price,
        min_prior_volume=min_prior_volume,
    )
    union_eligible = sorted({ticker for names in eligible.values() for ticker in names})
    print(f"prior-only eligible union={len(union_eligible):,}")

    # Exact 09:30-09:35 one-minute history for RVOL. Pull the union across the
    # context period so a ticker does not need to have been selected previously.
    opening_frames = []
    opening_sessions = context_sessions[-(days + history_sessions):]
    for no, session in enumerate(opening_sessions, start=1):
        frame = _fetch_frame(
            client,
            union_eligible,
            "1Min",
            et(session, 9, 30),
            et(session, 9, 36),
            session,
            context,
            batch_size=400,
            asof=session.isoformat(),
        )
        if not frame.empty:
            opening_frames.append(frame)
        print(f"opening {no:03d}/{len(opening_sessions)} {session} rows={len(frame):,}")
    opening = pd.concat(opening_frames, ignore_index=True) if opening_frames else pd.DataFrame()
    opening.to_csv(out / "opening_history.csv.gz", index=False, compression="gzip")

    # Broad signal-time scan. Five-minute bars are safe only through 09:19;
    # 09:20 onward is fetched at one-minute resolution for 09:25/09:29/09:31-35 freezes.
    signal_rows = []
    for no, session in enumerate(eval_sessions, start=1):
        names = eligible.get(session, [])
        if not names:
            continue
        pre5 = _fetch_frame(
            client, names, "5Min", et(session, 4), et(session, 9, 20), session, context, 400, asof=session.isoformat()
        )
        near1 = _fetch_frame(
            client, names, "1Min", et(session, 9, 20), et(session, 9, 36), session, context, 400, asof=session.isoformat()
        )
        scan = pd.concat([pre5, near1], ignore_index=True) if not pre5.empty or not near1.empty else pd.DataFrame()
        if scan.empty:
            continue
        for ticker, day_bars in scan.groupby("ticker", sort=False):
            ctx = context.get((ticker, session), {})
            hist = _history_for(opening, ticker, session.isoformat(), history_sessions)
            snaps = build_snapshots(day_bars, hist)
            if snaps.empty:
                continue
            snaps["prior20_median_volume"] = ctx.get("prior20_median_volume")
            snaps["prior20_max_volume"] = ctx.get("prior20_max_volume")
            snaps["prior4d_return"] = ctx.get("prior4d_return")
            signal_rows.append(snaps)
        print(f"signal scan {no:03d}/{len(eval_sessions)} {session} eligible={len(names)}")

    signal_snapshots = pd.concat(signal_rows, ignore_index=True) if signal_rows else pd.DataFrame()
    signal_snapshots.to_csv(out / "signal_time_snapshots.csv.gz", index=False, compression="gzip")
    candidates = select_signal_time_candidates(
        signal_snapshots,
        min_price=min_price,
        max_price=max_price,
        min_prior_volume=min_prior_volume,
        max_active=max_active_per_day,
        random_controls=random_controls_per_day,
    )
    candidates = _attach_retrospective_diagnostics(candidates, context)
    candidates.to_csv(out / "candidate_manifest.csv", index=False)
    print(f"signal-time candidate stock-days={len(candidates):,}")

    # Full-day one-minute history is downloaded only after the no-future selector.
    minute_frames = []
    by_date = {d: set(g["ticker"].astype(str)) for d, g in candidates.groupby("session_date")} if not candidates.empty else {}
    for no, session in enumerate(eval_sessions, start=1):
        names = sorted(by_date.get(session.isoformat(), set()))
        if not names:
            continue
        frame = _fetch_frame(
            client,
            names,
            "1Min",
            et(session, 4),
            et(session, 16, 1),
            session,
            context,
            batch_size=80,
            asof=session.isoformat(),
        )
        if not frame.empty:
            minute_frames.append(frame)
        print(f"full minute {no:03d}/{len(eval_sessions)} {session} candidates={len(names)} rows={len(frame):,}")
    minute = pd.concat(minute_frames, ignore_index=True) if minute_frames else pd.DataFrame()
    minute.to_csv(out / "minute_selected.csv.gz", index=False, compression="gzip")

    labeled = assemble_labeled_snapshots(
        minute,
        opening,
        candidates,
        history_sessions=history_sessions,
    )
    labeled.to_csv(out / "snapshots_labeled.csv.gz", index=False, compression="gzip")

    manifest = {
        "feed": client.feed,
        "sessions": len(eval_sessions),
        "start": eval_sessions[0].isoformat(),
        "end": eval_sessions[-1].isoformat(),
        "universe": len(symbols),
        "prior_eligible_union": len(union_eligible),
        "candidate_stock_days": len(candidates),
        "signal_snapshot_rows": len(signal_snapshots),
        "full_minute_rows": len(minute),
        "labeled_snapshot_rows": len(labeled),
        "selection": {
            "information_cutoff": "09:35 America/New_York",
            "max_signal_active_per_day": max_active_per_day,
            "random_controls_per_day": random_controls_per_day,
            "price_range": [min_price, max_price],
            "min_prior20_median_volume": min_prior_volume,
        },
        "external_holdout": "2026-08-12 through 2026-08-27 remains unopened",
        "limitations": [
            "Microcap is currently a prior-price/liquidity proxy; point-in-time market cap and float are not available in the bar source and are not fabricated.",
            "Historical NBBO/spread is not joined; execution uses next-minute open plus modeled adverse slippage.",
            "Short borrow/locate availability and locate fees are not available; short results are research-only.",
            "Catalyst text and dilution/ATM/warrant state are not yet joined point-in-time.",
            "Asset reference data can retain listing/symbol-history survivorship limitations.",
            "Retrospective daily H/L labels are attached only after candidate selection and never enter the signal-time gate.",
        ],
    }
    (out / "dataset_manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest
