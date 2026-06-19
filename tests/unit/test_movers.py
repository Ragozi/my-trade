"""Tests for the pure parsing of Alpaca screener responses (movers/most-actives).

The ``AlpacaMoversUniverse`` class itself is a fail-safe I/O boundary; here we
pin the deterministic symbol extraction it relies on.
"""

from __future__ import annotations

from types import SimpleNamespace

from my_trade.data.alpaca_movers import most_actives_symbols, movers_symbols


def _active(symbol: str, volume: float) -> SimpleNamespace:
    return SimpleNamespace(symbol=symbol, volume=volume, trade_count=1)


def _mover(symbol: str, pct: float) -> SimpleNamespace:
    return SimpleNamespace(symbol=symbol, percent_change=pct, price=10.0)


class TestMostActives:
    def test_orders_and_caps(self) -> None:
        items = [_active("AAA", 100), _active("BBB", 200), _active("CCC", 300)]
        assert most_actives_symbols(items, top=2) == ["AAA", "BBB"]

    def test_min_volume_filter(self) -> None:
        items = [_active("AAA", 100), _active("BBB", 5000)]
        assert most_actives_symbols(items, top=10, min_volume=1000) == ["BBB"]

    def test_exclude_and_dedup(self) -> None:
        items = [_active("AAA", 100), _active("aaa", 100), _active("SPY", 100)]
        assert most_actives_symbols(items, top=10, exclude=["spy"]) == ["AAA"]

    def test_skips_blank_symbols(self) -> None:
        items = [_active("", 100), _active("AAA", 100)]
        assert most_actives_symbols(items, top=10) == ["AAA"]


class TestMovers:
    def test_gainers_only(self) -> None:
        gainers = [_mover("UP1", 5.0), _mover("UP2", 4.0)]
        losers = [_mover("DN1", -5.0)]
        assert movers_symbols(gainers, losers, direction="gainers", top=10) == ["UP1", "UP2"]

    def test_losers_only(self) -> None:
        gainers = [_mover("UP1", 5.0)]
        losers = [_mover("DN1", -5.0), _mover("DN2", -4.0)]
        assert movers_symbols(gainers, losers, direction="losers", top=10) == ["DN1", "DN2"]

    def test_both_gainers_first(self) -> None:
        gainers = [_mover("UP1", 5.0)]
        losers = [_mover("DN1", -5.0)]
        assert movers_symbols(gainers, losers, direction="both", top=10) == ["UP1", "DN1"]

    def test_caps_and_excludes(self) -> None:
        gainers = [_mover("UP1", 5.0), _mover("UP2", 4.0), _mover("UP3", 3.0)]
        result = movers_symbols(gainers, [], direction="gainers", top=2, exclude=["UP1"])
        assert result == ["UP2", "UP3"]
