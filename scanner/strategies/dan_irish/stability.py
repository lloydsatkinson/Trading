from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd

from .config import IMPULSE_GRID, PULLBACK_DEPTH_GRID, RETAINED_GAIN_GRID, TURNOVER_GRID


THRESHOLD_COLUMNS = (
    "min_impulse_pct",
    "min_dollar_turnover",
    "min_retained_gain",
    "max_pullback_depth",
)

THRESHOLD_GRIDS = {
    "min_impulse_pct": tuple(float(x) for x in IMPULSE_GRID),
    "min_dollar_turnover": tuple(float(x) for x in TURNOVER_GRID),
    "min_retained_gain": tuple(float(x) for x in RETAINED_GAIN_GRID),
    "max_pullback_depth": tuple(float(x) for x in PULLBACK_DEPTH_GRID),
}

IDENTITY_COLUMNS = (
    "strategy_id",
    "variant_id",
    "setup_id",
    "rule_id",
    "split",
    "slippage_bps",
)


def _as_float(value, default=np.nan) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return float(default)
    return out if np.isfinite(out) or np.isinf(out) else float(default)


def _grid_index(grid: tuple[float, ...], value: float) -> int | None:
    for idx, candidate in enumerate(grid):
        if np.isclose(float(candidate), float(value), rtol=0.0, atol=max(1e-12, abs(float(candidate)) * 1e-12)):
            return idx
    return None


def _threshold_key(row: pd.Series | dict) -> tuple[float, ...]:
    return tuple(float(row[column]) for column in THRESHOLD_COLUMNS)


def summarize_dan_threshold_stability(
    threshold_summary: pd.DataFrame,
    min_n: int = 20,
    profitable_pf: float = 1.0,
    profitable_expectancy: float = 0.0,
) -> pd.DataFrame:
    """Measure whether a Dan threshold result sits on a profitable parameter plateau.

    Immediate orthogonal neighbours are defined by the approved threshold grids.
    Missing neighbours count against stability rather than being silently ignored;
    this prevents sparse, one-cell optima from looking robust.
    """
    if threshold_summary is None or threshold_summary.empty:
        return pd.DataFrame()

    required = set(IDENTITY_COLUMNS) | set(THRESHOLD_COLUMNS) | {
        "n",
        "expectancy",
        "profit_factor",
    }
    if not required.issubset(threshold_summary.columns):
        return pd.DataFrame()

    x = threshold_summary.copy()
    for column in THRESHOLD_COLUMNS:
        x[column] = pd.to_numeric(x[column], errors="coerce")
    x["n"] = pd.to_numeric(x["n"], errors="coerce")
    x["expectancy"] = pd.to_numeric(x["expectancy"], errors="coerce")
    x["profit_factor"] = pd.to_numeric(x["profit_factor"], errors="coerce")
    x = x.dropna(subset=list(THRESHOLD_COLUMNS) + ["n", "expectancy", "profit_factor"])
    if x.empty:
        return pd.DataFrame()

    rows: list[dict] = []
    group_cols = list(IDENTITY_COLUMNS)
    for identity_values, group in x.groupby(group_cols, dropna=False, sort=False):
        identity_values = identity_values if isinstance(identity_values, tuple) else (identity_values,)
        identity = dict(zip(group_cols, identity_values))
        group = group.drop_duplicates(list(THRESHOLD_COLUMNS), keep="first").copy()
        lookup = {_threshold_key(row): row for _, row in group.iterrows()}

        for _, row in group.iterrows():
            current_key = list(_threshold_key(row))
            possible_neighbor_n = 0
            observed_neighbor_n = 0
            stable_neighbor_n = 0
            observed_expectancies: list[float] = []
            observed_pfs: list[float] = []

            for dimension, column in enumerate(THRESHOLD_COLUMNS):
                grid = THRESHOLD_GRIDS[column]
                position = _grid_index(grid, current_key[dimension])
                if position is None:
                    continue
                for neighbour_position in (position - 1, position + 1):
                    if neighbour_position < 0 or neighbour_position >= len(grid):
                        continue
                    possible_neighbor_n += 1
                    neighbour_key = list(current_key)
                    neighbour_key[dimension] = float(grid[neighbour_position])
                    neighbour = lookup.get(tuple(neighbour_key))
                    if neighbour is None:
                        continue
                    observed_neighbor_n += 1
                    neighbour_n = int(_as_float(neighbour.get("n"), 0.0))
                    neighbour_expectancy = _as_float(neighbour.get("expectancy"))
                    neighbour_pf = _as_float(neighbour.get("profit_factor"))
                    observed_expectancies.append(neighbour_expectancy)
                    observed_pfs.append(neighbour_pf)
                    if (
                        neighbour_n >= int(min_n)
                        and neighbour_expectancy > float(profitable_expectancy)
                        and neighbour_pf >= float(profitable_pf)
                    ):
                        stable_neighbor_n += 1

            self_n = int(_as_float(row.get("n"), 0.0))
            self_expectancy = _as_float(row.get("expectancy"))
            self_pf = _as_float(row.get("profit_factor"))
            self_qualifies = bool(
                self_n >= int(min_n)
                and self_expectancy > float(profitable_expectancy)
                and self_pf >= float(profitable_pf)
            )
            plateau_stability = (
                float(stable_neighbor_n / possible_neighbor_n)
                if possible_neighbor_n > 0
                else np.nan
            )

            rows.append({
                **identity,
                **{column: float(row[column]) for column in THRESHOLD_COLUMNS},
                "n": self_n,
                "expectancy": self_expectancy,
                "profit_factor": self_pf,
                "self_qualifies": self_qualifies,
                "possible_neighbor_n": int(possible_neighbor_n),
                "observed_neighbor_n": int(observed_neighbor_n),
                "stable_neighbor_n": int(stable_neighbor_n),
                "plateau_stability": plateau_stability,
                "observed_neighbor_min_expectancy": (
                    float(np.min(observed_expectancies)) if observed_expectancies else np.nan
                ),
                "observed_neighbor_median_expectancy": (
                    float(np.median(observed_expectancies)) if observed_expectancies else np.nan
                ),
                "observed_neighbor_min_profit_factor": (
                    float(np.min(observed_pfs)) if observed_pfs else np.nan
                ),
            })

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(
        ["self_qualifies", "plateau_stability", "expectancy", "profit_factor", "n"],
        ascending=[False, False, False, False, False],
        na_position="last",
    ).reset_index(drop=True)
