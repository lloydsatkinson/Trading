from __future__ import annotations

from dataclasses import asdict
import itertools
from typing import Iterable, Sequence

import pandas as pd

from .prerunner import ExecutionRule, build_snapshots, label_snapshot, simulate_snapshot_trade
from .prerunner_optimizer import performance_metrics
from .prerunner_search import SnapshotRule, rule_mask


def _date_col(frame: pd.DataFrame) -> str:
    if "session_date" in frame.columns:
        return "session_date"
    if "date" in frame.columns:
        return "date"
    raise ValueError("frame requires session_date or date")


def _history_window(opening_history: pd.DataFrame, ticker: str, session_date: str, history_sessions: int) -> pd.DataFrame:
    if opening_history is None or opening_history.empty:
        return pd.DataFrame()
    h = opening_history.copy()
    h["ticker"] = h["ticker"].astype(str).str.upper()
    dc = _date_col(h)
    h[dc] = h[dc].astype(str)
    dates = sorted(d for d in h.loc[h["ticker"] == ticker, dc].unique() if d < session_date)
    keep = set(dates[-history_sessions:])
    return h[(h["ticker"] == ticker) & h[dc].isin(keep)].copy()


def assemble_labeled_snapshots(
    minute: pd.DataFrame,
    opening_history: pd.DataFrame,
    candidate_manifest: pd.DataFrame,
    *,
    freeze_times: Sequence[str] = ("09:25", "09:29", "09:31", "09:32", "09:33", "09:34", "09:35"),
    history_sessions: int = 14,
) -> pd.DataFrame:
    """Recompute exact one-minute snapshots for selected stock-days, then label future paths.

    Selection has already happened upstream using signal-time data. Future bars are
    exposed only to `label_snapshot`, after all feature columns are frozen.
    """
    if minute.empty or candidate_manifest.empty:
        return pd.DataFrame()
    m = minute.copy()
    m["ticker"] = m["ticker"].astype(str).str.upper()
    dc = _date_col(m)
    m[dc] = m[dc].astype(str)
    manifest = candidate_manifest.copy()
    manifest["ticker"] = manifest["ticker"].astype(str).str.upper()
    manifest["session_date"] = manifest["session_date"].astype(str)

    rows: list[dict] = []
    for _, meta in manifest.iterrows():
        ticker = str(meta["ticker"])
        session_date = str(meta["session_date"])
        day = m[(m["ticker"] == ticker) & (m[dc] == session_date)].copy()
        if day.empty:
            continue
        history = _history_window(opening_history, ticker, session_date, history_sessions)
        snaps = build_snapshots(day, history, freeze_times=freeze_times)
        if snaps.empty:
            continue
        for c, value in meta.items():
            if c not in {"ticker", "session_date"}:
                snaps[c] = value
        for _, snapshot in snaps.iterrows():
            base = snapshot.to_dict()
            outcome = label_snapshot(day, snapshot["signal_ts"])
            if not outcome:
                continue
            base.update(outcome)
            rows.append(base)
    return pd.DataFrame(rows)


def _minute_groups(minute: pd.DataFrame) -> dict[tuple[str, str], pd.DataFrame]:
    if minute.empty:
        return {}
    m = minute.copy()
    m["ticker"] = m["ticker"].astype(str).str.upper()
    dc = _date_col(m)
    m[dc] = m[dc].astype(str)
    return {(str(t), str(d)): g.copy() for (t, d), g in m.groupby(["ticker", dc], sort=False)}


def rule_signal_rows(snapshots: pd.DataFrame, rule: SnapshotRule, split: str | None = None) -> pd.DataFrame:
    x = snapshots.copy()
    if split is not None:
        if "split" not in x.columns:
            raise ValueError("split requested but snapshots has no split column")
        x = x[x["split"].astype(str) == str(split)]
    mask = rule_mask(x, rule)
    chosen = x.loc[mask].copy()
    if chosen.empty:
        return chosen
    chosen["ticker"] = chosen["ticker"].astype(str).str.upper()
    chosen["session_date"] = chosen["session_date"].astype(str)
    chosen["signal_ts"] = pd.to_datetime(chosen["signal_ts"], utc=True, errors="coerce")
    chosen = chosen.dropna(subset=["signal_ts"]).sort_values(["session_date", "ticker", "signal_ts"])
    return chosen.drop_duplicates(["session_date", "ticker"], keep="first").reset_index(drop=True)


def replay_rule(
    snapshots: pd.DataFrame,
    minute: pd.DataFrame,
    rule: SnapshotRule,
    execution: ExecutionRule,
    *,
    split: str | None = None,
    minute_groups: dict[tuple[str, str], pd.DataFrame] | None = None,
) -> pd.DataFrame:
    signals = rule_signal_rows(snapshots, rule, split=split)
    groups = minute_groups if minute_groups is not None else _minute_groups(minute)
    rows: list[dict] = []
    for _, signal in signals.iterrows():
        ticker = str(signal["ticker"]).upper()
        session_date = str(signal["session_date"])
        bars = groups.get((ticker, session_date))
        if bars is None or bars.empty:
            continue
        trade = simulate_snapshot_trade(bars, signal["signal_ts"], rule.side, execution)
        if trade is None:
            continue
        row = asdict(trade)
        row.update({
            "rule_id": rule.rule_id,
            "session_date": session_date,
            "ticker": ticker,
            "split": str(signal.get("split", split or "")),
            "freeze_time": rule.freeze_time,
            "stop_pct": execution.stop_pct,
            "target_pct": execution.target_pct,
            "max_hold_minutes": execution.max_hold_minutes,
            "slippage_bps": execution.slippage_bps,
        })
        rows.append(row)
    return pd.DataFrame(rows)


def execution_rule_grid(
    *,
    stops: Iterable[float] = (0.03, 0.05, 0.08, 0.12),
    targets: Iterable[float] = (0.06, 0.10, 0.15, 0.20, 0.30),
    holds: Iterable[int] = (15, 30, 60),
    slippage_bps: float = 20.0,
) -> list[ExecutionRule]:
    return [
        ExecutionRule(float(stop), float(target), int(hold), float(slippage_bps))
        for stop, target, hold in itertools.product(stops, targets, holds)
    ]


def evaluate_execution_grid(
    snapshots: pd.DataFrame,
    minute: pd.DataFrame,
    rules: Sequence[SnapshotRule],
    executions: Sequence[ExecutionRule],
    *,
    split: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    groups = _minute_groups(minute)
    sessions = max(1, snapshots.loc[snapshots["split"].astype(str) == split, "session_date"].astype(str).nunique())
    metrics_rows: list[dict] = []
    all_trades: list[pd.DataFrame] = []
    for rule in rules:
        for no, execution in enumerate(executions, start=1):
            trades = replay_rule(
                snapshots,
                minute,
                rule,
                execution,
                split=split,
                minute_groups=groups,
            )
            if trades.empty:
                continue
            trades = trades.copy()
            execution_id = f"S{execution.stop_pct:.3f}_T{execution.target_pct:.3f}_H{execution.max_hold_minutes}_B{execution.slippage_bps:.0f}"
            trades["execution_id"] = execution_id
            all_trades.append(trades)
            metrics = performance_metrics(trades, side=rule.side, sessions=sessions)
            metrics.update({
                "rule_id": rule.rule_id,
                "execution_id": execution_id,
                "split": split,
                "stop_pct": execution.stop_pct,
                "target_pct": execution.target_pct,
                "max_hold_minutes": execution.max_hold_minutes,
                "slippage_bps": execution.slippage_bps,
            })
            metrics_rows.append(metrics)
    metrics_frame = pd.DataFrame(metrics_rows)
    trades_frame = pd.concat(all_trades, ignore_index=True) if all_trades else pd.DataFrame()
    return metrics_frame, trades_frame
