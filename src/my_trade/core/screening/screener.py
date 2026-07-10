"""Screener: turns a candidate universe into a ranked, tradeable watchlist.

It is a thin orchestrator over already-tested pure pieces:

    UniverseSource (symbols)  ->  MarketDataProvider (bars)
        ->  metrics.build_candidate  ->  filters.rank  ->  watchlist

It is deterministic given the same data, fail-safe (a bad symbol or data
outage is skipped, never fatal), and cached: ``select`` only re-screens after
``refresh_seconds`` so it can be called every cycle cheaply.

It makes no trading decisions and never touches risk or execution — it only
narrows *which* symbols the orchestrator scans.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from my_trade.data import MarketDataProvider

from my_trade.core.market_calendar import is_am_momentum_window

from .filters import rank
from .metrics import build_candidate
from .models import Candidate, ScreenerCriteria
from .universe import UniverseSource


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Screener:
    """Builds and caches a ranked watchlist from a universe + market data."""

    def __init__(
        self,
        *,
        data: MarketDataProvider,
        universe: UniverseSource,
        criteria: ScreenerCriteria,
        timeframe: str = "15Min",
        bar_limit: int = 50,
        atr_period: int = 14,
        lookback: int = 20,
        refresh_seconds: int = 900,
        am_refresh_seconds: int = 0,
        clock: Callable[[], datetime] = _utcnow,
        logger: logging.Logger | None = None,
    ) -> None:
        criteria.validate()
        self._data = data
        self._universe = universe
        self._criteria = criteria
        self._timeframe = timeframe
        self._bar_limit = bar_limit
        self._atr_period = atr_period
        self._lookback = lookback
        self._refresh_seconds = refresh_seconds
        self._am_refresh_seconds = max(0, am_refresh_seconds)
        self._clock = clock
        self._log = logger or logging.getLogger("my_trade.screening")
        self._last_run: datetime | None = None
        self._ranked: list[Candidate] = []

    @property
    def ranked(self) -> list[Candidate]:
        """The most recent ranked candidates (with scores), for observability."""
        return list(self._ranked)

    def screen(self) -> list[Candidate]:
        """Run a full screening pass now and return ranked candidates."""
        now = self._clock()
        as_of = now.date()
        candidates: list[Candidate] = []
        for symbol in self._universe.symbols():
            try:
                bars = self._data.get_bars(symbol, self._timeframe, self._bar_limit)
            except Exception as exc:  # fail safe: skip a bad symbol, keep screening
                self._log.warning("screener: bars failed for %s: %s", symbol, exc)
                continue
            daily = None
            try:
                daily = self._data.get_bars(symbol, "1Day", 10)
            except Exception as exc:
                self._log.debug("screener: daily bars failed for %s: %s", symbol, exc)
            candidate = build_candidate(
                symbol,
                bars,
                atr_period=self._atr_period,
                lookback=self._lookback,
                daily=daily,
                as_of=as_of,
            )
            if candidate is not None:
                candidates.append(candidate)

        ranked = rank(candidates, self._criteria)
        self._ranked = ranked
        self._last_run = now
        gap_bits = [
            f"{c.symbol}(gap={c.gap_pct:+.1%})" for c in ranked if abs(c.gap_pct) >= 0.01
        ]
        self._log.info(
            "screener: %d/%d candidates passed -> %s%s",
            len(ranked),
            len(candidates),
            [c.symbol for c in ranked],
            f" overnight={gap_bits}" if gap_bits else "",
        )
        return ranked

    def _effective_refresh_seconds(self, now: datetime) -> int:
        if self._am_refresh_seconds > 0 and is_am_momentum_window(now):
            return self._am_refresh_seconds
        return self._refresh_seconds

    def _is_stale(self, now: datetime) -> bool:
        if self._last_run is None:
            return True
        return (now - self._last_run).total_seconds() >= self._effective_refresh_seconds(now)

    def select(self) -> Sequence[str]:
        """Return the cached watchlist, re-screening only when it's stale.

        Designed to be passed directly as the orchestrator's watchlist hook.
        """
        if self._is_stale(self._clock()):
            self.screen()
        return tuple(c.symbol for c in self._ranked)
