from __future__ import annotations

from dataclasses import asdict, dataclass
import itertools
import json
import math
from typing import Sequence

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Clause:
    feature: str
    op: str
    threshold: float


@dataclass(frozen=True)
class SnapshotRule:
    rule_id: str
    side: str
    freeze_time: str
    clauses: tuple[Clause, ...]


def assign_chronological_splits(
    frame: pd.DataFrame,
    date_col: str = "session_date",
    development_fraction: float = 0.60,
    validation_fraction: float = 0.20,
) -> pd.DataFrame:
    if date_col not in frame.columns:
        raise ValueError(f"missing {date_col}")
    if development_fraction <= 0 or validation_fraction <= 0 or development_fraction + validation_fraction >= 1:
        raise ValueError("invalid split fractions")
    x = frame.copy()
    dates = sorted(pd.Series(x[date_col].astype(str).unique()).tolist())
    n = len(dates)
    if n < 3:
        raise ValueError("at least three sessions are required")
    n_dev = max(1, int(math.floor(n * development_fraction)))
    n_val = max(1, int(math.floor(n * validation_fraction)))
    if n_dev + n_val >= n:
        n_val = max(1, n - n_dev - 1)
    dev = set(dates[:n_dev])
    val = set(dates[n_dev:n_dev + n_val])
    x["split"] = np.where(
        x[date_col].astype(str).isin(dev),
        "development",
        np.where(x[date_col].astype(str).isin(val), "validation", "test"),
    )
    return x


def _target_column(side: str, target_pct: int) -> str:
    s = str(side).upper()
    if s not in {"LONG", "SHORT"}:
        raise ValueError("side must be LONG or SHORT")
    return f"{s.lower()}_reach_{int(target_pct)}"


def _safe_numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan)


def feature_lift_table(
    frame: pd.DataFrame,
    side: str,
    target_pct: int = 20,
    features: Sequence[str] = (),
    quantiles: Sequence[float] = (0.20, 0.35, 0.50, 0.65, 0.80),
    min_signals: int = 20,
    split_col: str = "split",
    development_label: str = "development",
) -> pd.DataFrame:
    """Measure event lift for transparent one-feature clauses using dev data only."""
    target = _target_column(side, target_pct)
    required = {split_col, "freeze_time", target}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"missing {sorted(missing)}")
    dev = frame[frame[split_col] == development_label].copy()
    rows: list[dict] = []
    for freeze, g in dev.groupby("freeze_time", sort=True):
        y = g[target].astype(bool)
        baseline = float(y.mean()) if len(y) else np.nan
        if not np.isfinite(baseline):
            continue
        for feature in features:
            if feature not in g.columns:
                continue
            values = _safe_numeric(g[feature])
            valid = values.notna()
            if int(valid.sum()) < min_signals:
                continue
            thresholds = []
            for q in quantiles:
                if not 0 <= float(q) <= 1:
                    raise ValueError("quantiles must be between 0 and 1")
                thresholds.append((float(q), float(values[valid].quantile(float(q)))))
            for q, threshold in thresholds:
                for op in (">=", "<="):
                    mask = valid & ((values >= threshold) if op == ">=" else (values <= threshold))
                    n = int(mask.sum())
                    if n < min_signals:
                        continue
                    rate = float(y[mask].mean())
                    lift = rate / baseline if baseline > 0 else (math.inf if rate > 0 else 0.0)
                    rows.append({
                        "side": str(side).upper(),
                        "target_pct": int(target_pct),
                        "freeze_time": str(freeze),
                        "feature": feature,
                        "op": op,
                        "quantile": q,
                        "threshold": threshold,
                        "n": n,
                        "baseline_rate": baseline,
                        "event_rate": rate,
                        "lift": float(lift),
                        "coverage": float(n / max(1, len(g))),
                    })
    return pd.DataFrame(rows)


def rule_mask(frame: pd.DataFrame, rule: SnapshotRule) -> pd.Series:
    mask = pd.Series(True, index=frame.index)
    if "freeze_time" not in frame.columns:
        raise ValueError("missing freeze_time")
    mask &= frame["freeze_time"].astype(str) == str(rule.freeze_time)
    for clause in rule.clauses:
        if clause.feature not in frame.columns:
            return pd.Series(False, index=frame.index)
        values = _safe_numeric(frame[clause.feature])
        if clause.op == ">=":
            mask &= values >= clause.threshold
        elif clause.op == "<=":
            mask &= values <= clause.threshold
        else:
            raise ValueError(f"unsupported op {clause.op}")
    return mask.fillna(False)


def score_rules(
    frame: pd.DataFrame,
    rules: Sequence[SnapshotRule],
    side: str,
    target_pct: int = 20,
    split: str = "validation",
) -> pd.DataFrame:
    target = _target_column(side, target_pct)
    if target not in frame.columns or "split" not in frame.columns:
        raise ValueError("missing target/split columns")
    g = frame[frame["split"] == split]
    baseline = float(g[target].astype(bool).mean()) if len(g) else np.nan
    rows = []
    for rule in rules:
        if rule.side != str(side).upper():
            continue
        m = rule_mask(g, rule)
        n = int(m.sum())
        rate = float(g.loc[m, target].astype(bool).mean()) if n else 0.0
        lift = rate / baseline if baseline and baseline > 0 else (math.inf if rate > 0 else 0.0)
        rows.append({
            "rule_id": rule.rule_id,
            "side": rule.side,
            "split": split,
            "n": n,
            "baseline_rate": baseline,
            "event_rate": rate,
            "lift": float(lift),
            "coverage": float(n / max(1, len(g))),
        })
    return pd.DataFrame(rows)


def discover_rules(
    frame: pd.DataFrame,
    side: str,
    target_pct: int = 20,
    features: Sequence[str] = (),
    quantiles: Sequence[float] = (0.20, 0.35, 0.50, 0.65, 0.80),
    min_signals: int = 20,
    top_single: int = 12,
    max_pairs: int = 24,
) -> list[SnapshotRule]:
    """Discover bounded 1-2 clause rules from the development split only."""
    side = str(side).upper()
    lift = feature_lift_table(
        frame,
        side=side,
        target_pct=target_pct,
        features=features,
        quantiles=quantiles,
        min_signals=min_signals,
    )
    if lift.empty:
        return []
    lift = lift.copy()
    lift["search_score"] = lift["lift"].replace([np.inf], 100.0) * np.sqrt(lift["coverage"].clip(lower=0))
    lift = lift.sort_values(["search_score", "n"], ascending=[False, False]).head(max(1, top_single))
    rules: list[SnapshotRule] = []
    meta: list[tuple[float, SnapshotRule]] = []
    for i, row in lift.reset_index(drop=True).iterrows():
        clause = Clause(str(row.feature), str(row.op), float(row.threshold))
        rule = SnapshotRule(f"{side}_S{i+1:02d}", side, str(row.freeze_time), (clause,))
        rules.append(rule)
        meta.append((float(row.search_score), rule))

    target = _target_column(side, target_pct)
    dev = frame[frame["split"] == "development"]
    pair_meta: list[tuple[float, SnapshotRule]] = []
    for a, b in itertools.combinations(rules, 2):
        if a.freeze_time != b.freeze_time:
            continue
        if a.clauses[0].feature == b.clauses[0].feature:
            continue
        clauses = (a.clauses[0], b.clauses[0])
        tmp = SnapshotRule("TMP", side, a.freeze_time, clauses)
        m = rule_mask(dev, tmp)
        n = int(m.sum())
        if n < min_signals:
            continue
        freeze_base = dev[dev["freeze_time"].astype(str) == a.freeze_time]
        baseline = float(freeze_base[target].astype(bool).mean()) if len(freeze_base) else 0.0
        rate = float(dev.loc[m, target].astype(bool).mean()) if n else 0.0
        lift_value = rate / baseline if baseline > 0 else (100.0 if rate > 0 else 0.0)
        coverage = n / max(1, len(freeze_base))
        score = float(lift_value * math.sqrt(max(0.0, coverage)))
        pair_meta.append((score, SnapshotRule("TMP", side, a.freeze_time, clauses)))
    pair_meta.sort(key=lambda z: z[0], reverse=True)
    for i, (score, rule) in enumerate(pair_meta[:max_pairs], start=1):
        final = SnapshotRule(f"{side}_P{i:02d}", side, rule.freeze_time, rule.clauses)
        rules.append(final)
        meta.append((score, final))

    seen = set()
    ordered = []
    for _, rule in sorted(meta, key=lambda z: (-z[0], z[1].rule_id)):
        key = (rule.side, rule.freeze_time, tuple((c.feature, c.op, round(c.threshold, 12)) for c in rule.clauses))
        if key in seen:
            continue
        seen.add(key)
        ordered.append(rule)
    return ordered


def rule_to_dict(rule: SnapshotRule) -> dict:
    return {
        "rule_id": rule.rule_id,
        "side": rule.side,
        "freeze_time": rule.freeze_time,
        "clauses": [asdict(c) for c in rule.clauses],
    }


def rule_from_dict(data: dict) -> SnapshotRule:
    return SnapshotRule(
        rule_id=str(data["rule_id"]),
        side=str(data["side"]).upper(),
        freeze_time=str(data["freeze_time"]),
        clauses=tuple(Clause(str(c["feature"]), str(c["op"]), float(c["threshold"])) for c in data["clauses"]),
    )


def rules_to_json(rules: Sequence[SnapshotRule]) -> str:
    return json.dumps([rule_to_dict(r) for r in rules], indent=2, sort_keys=True)
