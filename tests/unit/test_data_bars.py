"""Tests for the pure OHLCV bar helpers in my_trade.data.bars."""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import pytest

from my_trade.data import (
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
from my_trade.data.provider import MarketDataProvider


def _records(n: int, start: datetime, volume: float = 100.0) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for i in range(n):
        out.append(
            {
                "timestamp": start + timedelta(minutes=i),
                "open": 100.0 + i,
                "high": 101.0 + i,
                "low": 99.0 + i,
                "close": 100.5 + i,
                "volume": volume,
            }
        )
    return out


class TestSymbols:
    def test_normalize_symbol(self) -> None:
        assert normalize_symbol("btc/usd") == "BTCUSD"

    def test_symbols_match_across_formats(self) -> None:
        assert symbols_match("BTC/USD", "btcusd") is True
        assert symbols_match("BTC/USD", "ETH/USD") is False


class TestTimeframe:
    def test_known_timeframes(self) -> None:
        assert timeframe_to_seconds("1Min") == 60
        assert timeframe_to_seconds("15Min") == 900
        assert timeframe_to_seconds("1Hour") == 3600

    def test_unknown_timeframe_raises(self) -> None:
        with pytest.raises(ValueError):
            timeframe_to_seconds("3Min")


class TestBarsToFrame:
    def test_empty_records_return_empty_frame(self) -> None:
        df = bars_to_frame([])
        assert df.empty
        assert list(df.columns) == list(OHLCV_COLUMNS)

    def test_builds_sorted_indexed_frame(self) -> None:
        start = datetime(2026, 1, 1, 12, 0, 0)
        out_of_order = list(reversed(_records(3, start)))
        df = bars_to_frame(out_of_order)
        assert len(df) == 3
        assert df.index.is_monotonic_increasing
        assert df.index[0] == start
        for col in OHLCV_COLUMNS:
            assert col in df.columns

    def test_coerces_string_numbers(self) -> None:
        df = bars_to_frame(
            [
                {
                    "timestamp": datetime(2026, 1, 1),
                    "open": "100",
                    "high": "101",
                    "low": "99",
                    "close": "100.5",
                    "volume": "5",
                }
            ]
        )
        assert df.iloc[0]["close"] == pytest.approx(100.5)


class TestCleanBars:
    def test_drops_nan_ohlc_rows(self) -> None:
        df = bars_to_frame(_records(3, datetime(2026, 1, 1, 12, 0)))
        df.iloc[1, df.columns.get_loc("close")] = float("nan")
        cleaned = clean_bars(df)
        assert len(cleaned) == 2

    def test_drops_duplicate_timestamps_keeping_last(self) -> None:
        ts = datetime(2026, 1, 1, 12, 0)
        df = bars_to_frame(
            [
                {"timestamp": ts, "open": 1, "high": 1, "low": 1, "close": 10, "volume": 1},
                {"timestamp": ts, "open": 2, "high": 2, "low": 2, "close": 20, "volume": 2},
            ]
        )
        cleaned = clean_bars(df)
        assert len(cleaned) == 1
        assert cleaned.iloc[0]["close"] == pytest.approx(20.0)

    def test_clean_empty_is_empty(self) -> None:
        assert clean_bars(empty_frame()).empty


class TestForwardFillZeroVolume:
    def test_zero_volume_uses_previous(self) -> None:
        start = datetime(2026, 1, 1, 12, 0)
        df = bars_to_frame(_records(3, start, volume=100.0))
        df.iloc[2, df.columns.get_loc("volume")] = 0.0
        filled = forward_fill_zero_volume(df)
        assert filled.iloc[2]["volume"] == pytest.approx(100.0)

    def test_leading_zero_volume_becomes_zero(self) -> None:
        start = datetime(2026, 1, 1, 12, 0)
        df = bars_to_frame(_records(2, start, volume=0.0))
        filled = forward_fill_zero_volume(df)
        assert filled.iloc[0]["volume"] == pytest.approx(0.0)

    def test_does_not_mutate_input(self) -> None:
        start = datetime(2026, 1, 1, 12, 0)
        df = bars_to_frame(_records(2, start, volume=0.0))
        forward_fill_zero_volume(df)
        assert df.iloc[0]["volume"] == pytest.approx(0.0)


class TestStalenessAndMinBars:
    def test_has_min_bars(self) -> None:
        df = bars_to_frame(_records(5, datetime(2026, 1, 1, 12, 0)))
        assert has_min_bars(df, 5) is True
        assert has_min_bars(df, 6) is False
        assert has_min_bars(empty_frame(), 1) is False

    def test_empty_frame_is_stale(self) -> None:
        assert is_stale(empty_frame(), datetime(2026, 1, 1), 60) is True

    def test_fresh_frame_not_stale(self) -> None:
        start = datetime(2026, 1, 1, 12, 0)
        df = bars_to_frame(_records(3, start))  # last bar at 12:02
        now = start + timedelta(minutes=2, seconds=30)
        assert is_stale(df, now, timeframe_seconds=60, max_lag_bars=2) is False

    def test_old_frame_is_stale(self) -> None:
        start = datetime(2026, 1, 1, 12, 0)
        df = bars_to_frame(_records(3, start))  # last bar at 12:02
        now = start + timedelta(minutes=10)
        assert is_stale(df, now, timeframe_seconds=60, max_lag_bars=2) is True


class TestProviderProtocol:
    def test_fake_dataframe_provider_satisfies_protocol(self) -> None:
        class FakeProvider:
            def get_bars(
                self, symbol: str, timeframe: str, limit: int | None = None
            ) -> pd.DataFrame:
                return bars_to_frame(_records(3, datetime(2026, 1, 1, 12, 0)))

            def get_latest_price(self, symbol: str) -> float | None:
                return 100.5

        provider: MarketDataProvider = FakeProvider()
        assert isinstance(provider, MarketDataProvider)
        assert len(provider.get_bars("BTC/USD", "1Min")) == 3
        assert provider.get_latest_price("BTC/USD") == pytest.approx(100.5)
