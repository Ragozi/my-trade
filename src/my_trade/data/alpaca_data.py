"""Alpaca-backed ``MarketDataProvider`` (the market-data I/O boundary).

Thin on purpose: fetch crypto bars from Alpaca and hand the raw records to the
pure ``data.bars`` helpers for all cleaning/normalization. The fetch never
raises on an empty/failed result — it returns an empty frame so callers can
apply the "no data => no trade" rule (see ``MarketDataProvider``).

Not unit-tested at the network boundary; the pure helpers (``compute_start``,
``records_from_bars``) are covered, and the live path is integration-tested by
the paper-trading runner.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd

from .bars import (
    bars_to_frame,
    clean_bars,
    empty_frame,
    forward_fill_zero_volume,
    symbols_match,
    timeframe_to_seconds,
)

_log = logging.getLogger("my_trade.data.alpaca")


def _utcnow() -> datetime:
    return datetime.now(UTC)


def compute_start(end: datetime, timeframe: str, limit: int, buffer: int = 2) -> datetime:
    """Lookback window start for ``limit`` bars of ``timeframe`` ending at ``end``.

    The ``buffer`` over-fetches (crypto has gaps/partials) so cleaning still
    leaves enough bars. Pure and deterministic.
    """
    if limit <= 0:
        raise ValueError(f"limit must be positive, got {limit}")
    seconds = timeframe_to_seconds(timeframe) * limit * max(buffer, 1)
    return end - timedelta(seconds=seconds)


def records_from_bars(bars: Iterable[Any]) -> list[dict[str, object]]:
    """Convert Alpaca bar objects (duck-typed) into clean OHLCV records."""
    records: list[dict[str, object]] = []
    for bar in bars:
        records.append(
            {
                "timestamp": bar.timestamp,
                "open": float(bar.open),
                "high": float(bar.high),
                "low": float(bar.low),
                "close": float(bar.close),
                "volume": float(bar.volume),
            }
        )
    return records


def alpaca_timeframe(timeframe: str) -> Any:
    """Map our timeframe string to an Alpaca ``TimeFrame`` (shared crypto/equity).

    Raises ``ValueError`` for an unsupported timeframe.
    """
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

    mapping = {
        "1Min": TimeFrame(1, TimeFrameUnit.Minute),
        "2Min": TimeFrame(2, TimeFrameUnit.Minute),
        "5Min": TimeFrame(5, TimeFrameUnit.Minute),
        "15Min": TimeFrame(15, TimeFrameUnit.Minute),
        "30Min": TimeFrame(30, TimeFrameUnit.Minute),
        "1Hour": TimeFrame(1, TimeFrameUnit.Hour),
        "1Day": TimeFrame(1, TimeFrameUnit.Day),
    }
    if timeframe not in mapping:
        raise ValueError(f"unsupported timeframe {timeframe!r}")
    return mapping[timeframe]


def frame_from_barset(barset: Any, symbol: str, *, fill_zero_volume: bool = True) -> pd.DataFrame:
    """Extract a cleaned OHLCV frame for ``symbol`` from an Alpaca barset.

    Pure given a duck-typed ``barset`` (an object with a ``.data`` mapping of
    symbol -> bar list), so it is unit-testable without the network. Returns an
    empty frame when the symbol is absent/empty. ``fill_zero_volume`` is the
    crypto-only quirk fix (current candle reports volume==0); equities pass
    ``False``.
    """
    data = getattr(barset, "data", {}) or {}
    key: str | None = symbol if symbol in data else None
    if key is None:
        key = next((k for k in data if symbols_match(k, symbol)), None)
    if key is None or not data.get(key):
        return empty_frame()
    frame = bars_to_frame(records_from_bars(data[key]))
    frame = clean_bars(frame)
    return forward_fill_zero_volume(frame) if fill_zero_volume else frame


class AlpacaDataProvider:
    """Crypto OHLCV bars from Alpaca, cleaned via the pure data layer."""

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        *,
        default_limit: int = 200,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        from alpaca.data.historical import CryptoHistoricalDataClient

        self._client: Any = CryptoHistoricalDataClient(api_key=api_key, secret_key=api_secret)
        self._default_limit = default_limit
        self._clock = clock

    @classmethod
    def from_settings(cls, settings: Any) -> AlpacaDataProvider:
        return cls(
            settings.alpaca.api_key,
            settings.alpaca.api_secret,
            default_limit=settings.runtime.bar_limit,
        )

    def _timeframe(self, timeframe: str) -> Any:
        return alpaca_timeframe(timeframe)

    def get_bars(self, symbol: str, timeframe: str, limit: int | None = None) -> pd.DataFrame:
        bar_limit = limit or self._default_limit
        end = self._clock()
        start = compute_start(end, timeframe, bar_limit)
        try:
            from alpaca.data.requests import CryptoBarsRequest

            request = CryptoBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=self._timeframe(timeframe),
                start=start,
                end=end,
                limit=bar_limit,
            )
            barset = self._client.get_crypto_bars(request)
        except Exception as exc:  # boundary: degrade to "no data", never crash the loop
            _log.warning("get_bars failed for %s %s: %s", symbol, timeframe, exc)
            return empty_frame()

        return frame_from_barset(barset, symbol, fill_zero_volume=True)

    def get_latest_price(self, symbol: str) -> float | None:
        frame = self.get_bars(symbol, "1Min", limit=5)
        if frame.empty:
            return None
        return float(frame.iloc[-1]["close"])
