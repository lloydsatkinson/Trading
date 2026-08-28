from __future__ import annotations

from dataclasses import dataclass
import pandas as pd

Range = tuple[float, float]


@dataclass(frozen=True)
class RangeRule:
    name: str
    move_1d: Range | None = None
    prior4d: Range | None = None
    rvol: Range | None = None
    min_price: float | None = None
    max_price: float | None = None
    min_dollar_volume: float | None = None
    max_daily_rank: int | None = None
    require_fresh_sec_days: int | None = None

    @staticmethod
    def _range_mask(series: pd.Series, bounds: Range | None) -> pd.Series:
        if bounds is None:
            return pd.Series(True, index=series.index)
        lo, hi = bounds
        return series.ge(lo) & series.lt(hi)

    def mask(self, frame: pd.DataFrame) -> pd.Series:
        mask = pd.Series(True, index=frame.index)
        if self.move_1d is not None:
            mask &= self._range_mask(frame["move_1d"], self.move_1d)
        if self.prior4d is not None:
            mask &= self._range_mask(frame["prior4d"], self.prior4d)
        if self.rvol is not None:
            mask &= self._range_mask(frame["rvol"], self.rvol)
        if self.min_price is not None:
            mask &= frame["price"].ge(self.min_price)
        if self.max_price is not None:
            mask &= frame["price"].le(self.max_price)
        if self.min_dollar_volume is not None:
            mask &= frame["dollar_volume"].ge(self.min_dollar_volume)
        if self.max_daily_rank is not None:
            mask &= frame["daily_rank"].le(self.max_daily_rank)
        if self.require_fresh_sec_days is not None:
            mask &= frame[f"fresh_sec_{self.require_fresh_sec_days}d"].fillna(0).astype(float).gt(0)
        return mask.fillna(False)
