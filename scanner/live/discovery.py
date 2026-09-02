from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any
from zoneinfo import ZoneInfo

from scanner.multistrategy.config import MultiStrategyConfig

from .models import MarketBar

ET = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class DiscoveryDecision:
    symbol: str
    promoted: bool
    newly_promoted: bool
    reason_codes: tuple[str, ...]
    prior_close: float | None
    gap_pct: float | None
    activity_dollar: float


@dataclass
class _DiscoveryState:
    session_date: date
    activity_dollar: float = 0.0
    high: float = 0.0
    promoted: bool = False
    reason_codes: tuple[str, ...] = ()


class DiscoveryGate:
    def __init__(self, prior_close_by_symbol: dict[str, float], cfg: MultiStrategyConfig | None = None) -> None:
        self.prior_close_by_symbol = {
            str(symbol).upper(): float(value)
            for symbol, value in prior_close_by_symbol.items()
            if value is not None and float(value) > 0
        }
        self.cfg = cfg or MultiStrategyConfig()
        self._state: dict[str, _DiscoveryState] = {}

    @staticmethod
    def _session_date(bar: MarketBar) -> date:
        if bar.timestamp.tzinfo is None or bar.timestamp.utcoffset() is None:
            raise ValueError("bar timestamp must be timezone-aware")
        return bar.timestamp.astimezone(ET).date()

    def observe(self, bar: MarketBar) -> DiscoveryDecision:
        symbol = bar.symbol.upper()
        day = self._session_date(bar)
        state = self._state.get(symbol)
        if state is None or state.session_date != day:
            state = _DiscoveryState(session_date=day)
            self._state[symbol] = state

        typical = (float(bar.high) + float(bar.low) + float(bar.close)) / 3.0
        state.activity_dollar += max(0.0, typical) * max(0.0, float(bar.volume))
        state.high = max(state.high, float(bar.high), float(bar.close))

        prior_close = self.prior_close_by_symbol.get(symbol)
        gap_pct = None
        reasons: list[str] = []
        if prior_close is not None and prior_close > 0:
            gap_pct = float(bar.close) / prior_close - 1.0
            in_price_band = self.cfg.min_price <= float(bar.close) <= self.cfg.max_price
            if (
                in_price_band
                and abs(gap_pct) >= self.cfg.min_gap_pct
                and state.activity_dollar >= self.cfg.min_activity_dollar_turnover
            ):
                reasons.append("GAP_ACTIVITY")
            if (
                state.high / prior_close > 1.20
                and state.activity_dollar >= self.cfg.min_activity_dollar_turnover
            ):
                reasons.append("LEO_EXTENSION")

        qualifies = bool(reasons)
        newly_promoted = qualifies and not state.promoted
        if qualifies:
            state.promoted = True
            state.reason_codes = tuple(dict.fromkeys((*state.reason_codes, *reasons)))

        return DiscoveryDecision(
            symbol=symbol,
            promoted=state.promoted,
            newly_promoted=newly_promoted,
            reason_codes=state.reason_codes,
            prior_close=prior_close,
            gap_pct=gap_pct,
            activity_dollar=float(state.activity_dollar),
        )

    def promoted_symbols(self) -> frozenset[str]:
        return frozenset(symbol for symbol, state in self._state.items() if state.promoted)
