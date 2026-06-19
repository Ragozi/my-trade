"""Alpaca-backed ``MarketDataProvider`` for US equities (the stock I/O boundary).

Mirror of :class:`AlpacaDataProvider` but backed by ``StockHistoricalDataClient``
/ ``StockBarsRequest``. Thin on purpose: it fetches bars and delegates *all*
cleaning to the shared pure helpers in ``alpaca_data`` + ``data.bars``. Unlike
crypto it does **not** forward-fill zero volume (that is a crypto-candle quirk).

The fetch never raises on an empty/failed result — it returns an empty frame so
callers can apply the "no data => no trade" rule. The network path is exercised
by the paper runner; the pure windowing/extraction helpers are unit-tested.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from .alpaca_data import alpaca_timeframe, compute_start, frame_from_barset
from .bars import empty_frame

_log = logging.getLogger("my_trade.data.alpaca_stock")


def _utcnow() -> datetime:
    return datetime.now(UTC)


class StockHistoricalDataProvider:
    """US-equity OHLCV bars from Alpaca, cleaned via the shared data layer."""

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        *,
        default_limit: int = 200,
        feed: str = "iex",
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        from alpaca.data.historical import StockHistoricalDataClient

        self._client: Any = StockHistoricalDataClient(api_key=api_key, secret_key=api_secret)
        self._default_limit = default_limit
        self._feed = feed
        self._clock = clock

    @classmethod
    def from_settings(cls, settings: Any) -> StockHistoricalDataProvider:
        return cls(
            settings.alpaca.api_key,
            settings.alpaca.api_secret,
            default_limit=settings.runtime.bar_limit,
        )

    def _data_feed(self) -> Any:
        from alpaca.data.enums import DataFeed

        return {
            "iex": DataFeed.IEX,
            "sip": DataFeed.SIP,
        }.get(self._feed.lower(), DataFeed.IEX)

    def get_bars(self, symbol: str, timeframe: str, limit: int | None = None) -> pd.DataFrame:
        bar_limit = limit or self._default_limit
        end = self._clock()
        start = compute_start(end, timeframe, bar_limit)
        try:
            from alpaca.data.requests import StockBarsRequest

            request = StockBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=alpaca_timeframe(timeframe),
                start=start,
                end=end,
                limit=bar_limit,
                feed=self._data_feed(),
            )
            barset = self._client.get_stock_bars(request)
        except Exception as exc:  # boundary: degrade to "no data", never crash the loop
            _log.warning("get_bars failed for %s %s: %s", symbol, timeframe, exc)
            return empty_frame()

        return frame_from_barset(barset, symbol, fill_zero_volume=False)

    def get_latest_price(self, symbol: str) -> float | None:
        frame = self.get_bars(symbol, "1Min", limit=5)
        if frame.empty:
            return None
        return float(frame.iloc[-1]["close"])
