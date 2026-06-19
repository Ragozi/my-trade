"""Typed, dependency-free contracts for the deterministic screener.

A ``Candidate`` is one symbol summarized by liquidity/volatility metrics; the
``ScreenerCriteria`` is the (configurable) gate + ranking weights. Both are pure
data — no pandas, no Alpaca — so the filter/rank logic in ``filters.py`` is
trivially unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Candidate:
    """A screening candidate, summarized from recent bars.

    Attributes:
        symbol: The instrument symbol (config form, e.g. ``BTC/USD`` or ``AAPL``).
        last_price: Most recent close.
        dollar_volume: Average per-bar dollar volume (``close * volume``) over the
            metric lookback. A liquidity proxy that works for crypto and equities.
        atr_pct: Average True Range as a fraction of price (volatility proxy).
        change_pct: Fractional price change over the lookback window (momentum).
        bars: Number of bars the metrics were computed from.
        score: Composite rank score, assigned by ``filters.rank`` (0.0 until ranked).
    """

    symbol: str
    last_price: float
    dollar_volume: float
    atr_pct: float
    change_pct: float
    bars: int
    score: float = 0.0


@dataclass(frozen=True)
class ScreenerCriteria:
    """Deterministic gate + ranking weights for the screener.

    Filtering keeps only liquid, sensibly-priced, sufficiently-volatile names;
    ranking then orders survivors by a transparent weighted blend of volatility
    and (set-normalized) liquidity. ``top_n`` caps the resulting watchlist.
    """

    min_price: float = 0.0
    max_price: float = float("inf")
    min_dollar_volume: float = 0.0
    min_atr_pct: float = 0.0
    max_atr_pct: float = float("inf")
    min_bars: int = 20
    top_n: int = 5
    weight_volatility: float = 1.0
    weight_liquidity: float = 1.0

    def validate(self) -> None:
        if self.min_price < 0:
            raise ValueError("min_price must be >= 0")
        if self.max_price < self.min_price:
            raise ValueError("max_price must be >= min_price")
        if self.min_dollar_volume < 0:
            raise ValueError("min_dollar_volume must be >= 0")
        if self.min_atr_pct < 0:
            raise ValueError("min_atr_pct must be >= 0")
        if self.max_atr_pct < self.min_atr_pct:
            raise ValueError("max_atr_pct must be >= min_atr_pct")
        if self.min_bars < 1:
            raise ValueError("min_bars must be >= 1")
        if self.top_n < 1:
            raise ValueError("top_n must be >= 1")
        if self.weight_volatility < 0 or self.weight_liquidity < 0:
            raise ValueError("weights must be >= 0")
