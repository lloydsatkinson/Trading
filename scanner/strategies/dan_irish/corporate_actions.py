from __future__ import annotations

from typing import Any

import pandas as pd


def _date(value: Any):
    if value is None or pd.isna(value):
        return None
    return pd.Timestamp(value).date()


def mark_corporate_action_replays(
    replays: pd.DataFrame,
    corporate_actions: pd.DataFrame,
) -> pd.DataFrame:
    """Flag Dan replays whose realised hold overlaps a confirmed split action.

    Corporate actions are audit exclusions, not return repairs. A flagged replay
    remains in raw artifacts but cannot contribute to production-selection metrics.
    """
    x = replays.copy()
    if x.empty:
        return x

    x["corporate_action_flag"] = False
    x["corporate_action_type"] = None
    x["corporate_action_date"] = None
    if corporate_actions is None or corporate_actions.empty:
        return x

    required_replay = {"symbol", "entry_timestamp", "exit_timestamp"}
    required_action = {"symbol", "action_type", "action_date"}
    if not required_replay.issubset(x.columns) or not required_action.issubset(corporate_actions.columns):
        return x

    actions = corporate_actions.copy()
    actions["symbol"] = actions["symbol"].astype(str).str.upper()
    actions["_action_date"] = actions["action_date"].map(_date)
    actions = actions[actions["_action_date"].notna()].copy()
    if actions.empty:
        return x

    if "selection_eligible_replay" not in x.columns:
        x["selection_eligible_replay"] = True

    for idx, replay in x.iterrows():
        entry_date = _date(replay.get("entry_timestamp"))
        exit_date = _date(replay.get("exit_timestamp"))
        if entry_date is None or exit_date is None:
            continue
        symbol = str(replay.get("symbol") or "").upper()
        overlapping = actions[
            actions["symbol"].eq(symbol)
            & actions["_action_date"].ge(entry_date)
            & actions["_action_date"].le(exit_date)
        ]
        if overlapping.empty:
            continue
        action_types = sorted({str(value) for value in overlapping["action_type"].dropna()})
        action_dates = sorted({str(value) for value in overlapping["_action_date"].dropna()})
        x.at[idx, "corporate_action_flag"] = True
        x.at[idx, "corporate_action_type"] = "|".join(action_types)
        x.at[idx, "corporate_action_date"] = "|".join(action_dates)
        x.at[idx, "selection_eligible_replay"] = False

    return x
