"""Tests for the shared Alpaca bar helpers used by both data providers.

The network calls are I/O boundaries (integration-tested via the paper runner);
here we cover the pure ``frame_from_barset`` extraction + ``alpaca_timeframe``
mapping that both the crypto and equity providers delegate to.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from my_trade.data.alpaca_data import alpaca_timeframe, frame_from_barset

T0 = datetime(2026, 6, 17, 14, 0, tzinfo=UTC)
T1 = datetime(2026, 6, 17, 14, 1, tzinfo=UTC)


def _bar(ts: datetime, close: float, volume: float) -> SimpleNamespace:
    return SimpleNamespace(
        timestamp=ts, open=close, high=close + 1, low=close - 1, close=close, volume=volume
    )


def _barset(data: dict[str, list[SimpleNamespace]]) -> SimpleNamespace:
    return SimpleNamespace(data=data)


class TestFrameFromBarset:
    def test_extracts_clean_frame(self) -> None:
        barset = _barset({"AAPL": [_bar(T0, 100, 1000), _bar(T1, 101, 1200)]})
        frame = frame_from_barset(barset, "AAPL", fill_zero_volume=False)
        assert list(frame.columns) == ["open", "high", "low", "close", "volume"]
        assert len(frame) == 2
        assert frame.iloc[-1]["close"] == 101.0

    def test_missing_symbol_returns_empty(self) -> None:
        barset = _barset({"AAPL": [_bar(T0, 100, 1000)]})
        assert frame_from_barset(barset, "MSFT").empty

    def test_empty_barset_returns_empty(self) -> None:
        assert frame_from_barset(_barset({}), "AAPL").empty

    def test_matches_crypto_symbol_without_slash(self) -> None:
        # Alpaca crypto keys are unslashed (BTCUSD) while config uses BTC/USD.
        barset = _barset({"BTCUSD": [_bar(T0, 50_000, 5), _bar(T1, 50_100, 6)]})
        frame = frame_from_barset(barset, "BTC/USD")
        assert len(frame) == 2

    def test_fill_zero_volume_true_forward_fills(self) -> None:
        barset = _barset({"BTC/USD": [_bar(T0, 100, 10), _bar(T1, 101, 0)]})
        frame = frame_from_barset(barset, "BTC/USD", fill_zero_volume=True)
        assert frame.iloc[-1]["volume"] == 10.0  # carried forward

    def test_fill_zero_volume_false_keeps_zero(self) -> None:
        barset = _barset({"AAPL": [_bar(T0, 100, 10), _bar(T1, 101, 0)]})
        frame = frame_from_barset(barset, "AAPL", fill_zero_volume=False)
        assert frame.iloc[-1]["volume"] == 0.0


class TestAlpacaTimeframe:
    def test_known_timeframe_returns_object(self) -> None:
        assert alpaca_timeframe("15Min") is not None

    def test_unknown_timeframe_raises(self) -> None:
        with pytest.raises(ValueError):
            alpaca_timeframe("7Min")
