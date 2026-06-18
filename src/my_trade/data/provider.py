"""The market-data boundary the rest of the system depends on.

Higher layers (strategy, monitoring, backtest) depend on this ``Protocol`` rather
than on Alpaca directly. The concrete Alpaca-backed implementation migrates from
the prototype's ``broker.py`` in a later Phase 1 step; backtests can supply a
DataFrame-backed fake that satisfies the same interface.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import pandas as pd


@runtime_checkable
class MarketDataProvider(Protocol):
    """Read-only source of OHLCV bars and latest price.

    Implementations MUST return frames cleaned via ``data.bars`` helpers
    (time-indexed, float OHLCV columns, ascending) and MUST NOT raise on an
    empty result — they return an empty frame / ``None`` instead, so callers can
    apply the "no data ⇒ no trade" rule.
    """

    def get_bars(self, symbol: str, timeframe: str, limit: int | None = None) -> pd.DataFrame:
        """Return cleaned OHLCV bars (empty frame if unavailable)."""
        ...

    def get_latest_price(self, symbol: str) -> float | None:
        """Return the latest trade/close price, or ``None`` if unavailable."""
        ...
