"""Tests for the pure helpers of the Alpaca data boundary.

The network path (`AlpacaDataProvider.get_bars`) is an I/O boundary tested by the
paper runner; here we cover the deterministic windowing + record conversion that
feed the existing pure ``data.bars`` cleaning functions.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from my_trade.data.alpaca_data import compute_start, records_from_bars
from my_trade.data.bars import bars_to_frame

END = datetime(2026, 6, 18, 14, 0, tzinfo=UTC)


class TestComputeStart:
    def test_window_scales_with_timeframe_limit_and_buffer(self) -> None:
        start = compute_start(END, "1Min", limit=100)  # default buffer=2
        assert (END - start).total_seconds() == 60 * 100 * 2

    def test_5min_window(self) -> None:
        start = compute_start(END, "5Min", limit=50, buffer=3)
        assert (END - start).total_seconds() == 300 * 50 * 3

    def test_rejects_non_positive_limit(self) -> None:
        with pytest.raises(ValueError):
            compute_start(END, "1Min", limit=0)

    def test_rejects_unknown_timeframe(self) -> None:
        with pytest.raises(ValueError):
            compute_start(END, "7Min", limit=10)


class TestRecordsFromBars:
    def _bar(self, ts: datetime, close: float) -> SimpleNamespace:
        return SimpleNamespace(
            timestamp=ts, open=close, high=close + 1, low=close - 1, close=close, volume=3.0
        )

    def test_converts_to_float_records(self) -> None:
        bars = [self._bar(END, 100), self._bar(END, 101)]
        records = records_from_bars(bars)
        assert len(records) == 2
        assert records[0]["close"] == 100.0
        assert isinstance(records[0]["volume"], float)

    def test_empty_input(self) -> None:
        assert records_from_bars([]) == []

    def test_records_feed_bars_to_frame(self) -> None:
        bars = [
            self._bar(datetime(2026, 6, 18, 13, 59, tzinfo=UTC), 100),
            self._bar(datetime(2026, 6, 18, 14, 0, tzinfo=UTC), 101),
        ]
        frame = bars_to_frame(records_from_bars(bars))
        assert list(frame.columns) == ["open", "high", "low", "close", "volume"]
        assert len(frame) == 2
        assert frame.iloc[-1]["close"] == 101.0
