"""Data layer: market data access, normalization, and persistence (I/O only).

Phase 1 migration target for the data-fetch parts of the prototype's `broker.py`
plus `journal.py`.

Responsibilities:
  - Wrap Alpaca data clients; return tidy, time-indexed pandas DataFrames.
  - Detect crypto realities explicitly: empty bars, stale timestamps, volume==0.
  - Persist daily snapshots + a SQLite journal of events/trades for audit/dashboard.

NON-responsibility: this layer makes NO trading decisions.
"""

from .bars import (
    OHLC_COLUMNS,
    OHLCV_COLUMNS,
    bars_to_frame,
    clean_bars,
    empty_frame,
    forward_fill_zero_volume,
    has_min_bars,
    is_stale,
    normalize_symbol,
    symbols_match,
    timeframe_to_seconds,
)
from .provider import MarketDataProvider

__all__ = [
    "OHLC_COLUMNS",
    "OHLCV_COLUMNS",
    "MarketDataProvider",
    "bars_to_frame",
    "clean_bars",
    "empty_frame",
    "forward_fill_zero_volume",
    "has_min_bars",
    "is_stale",
    "normalize_symbol",
    "symbols_match",
    "timeframe_to_seconds",
]
