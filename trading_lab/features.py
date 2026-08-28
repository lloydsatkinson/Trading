from __future__ import annotations

import pandas as pd


def add_signal_time_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Add features derivable from fields already known at signal time."""
    out = frame.copy()
    one = 1.0 + out["move_1d"].astype(float)
    five = 1.0 + out["move_5d"].astype(float)
    out["prior4d"] = five.div(one).sub(1.0)
    return out
