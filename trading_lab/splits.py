from __future__ import annotations

import numpy as np
import pandas as pd


def apply_standard_splits(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    dates = pd.to_datetime(out["date"])
    out["date"] = dates
    out["split"] = np.select(
        [dates.le("2025-12-31"), dates.between("2026-01-01", "2026-04-30"), dates.between("2026-05-01", "2026-06-30"), dates.between("2026-07-01", "2026-07-31")],
        ["dev", "val", "hold", "final"],
        default="other",
    )
    return out
