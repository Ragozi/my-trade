"""Tests for merged universe + symbol hygiene."""

from __future__ import annotations

from my_trade.core.screening.symbol_filters import is_blocked_symbol, merged_exclude_set
from my_trade.core.screening.universe import MergedUniverseSource, StaticUniverseSource


class _FixedSource:
    def __init__(self, symbols: tuple[str, ...]) -> None:
        self._symbols = symbols

    def symbols(self) -> tuple[str, ...]:
        return self._symbols


def test_merged_universe_dedupes_and_excludes() -> None:
    merged = MergedUniverseSource(
        _FixedSource(("NVDA", "AMD")),
        _FixedSource(("AMD", "SOXS", "TSLA")),
        exclude=merged_exclude_set(),
    )
    assert merged.symbols() == ("NVDA", "AMD", "TSLA")


def test_leveraged_etf_in_exclude_set() -> None:
    assert is_blocked_symbol("SOXS", exclude=merged_exclude_set())
    assert not is_blocked_symbol("NVDA", exclude=merged_exclude_set())


def test_large_cap_exclude_when_enabled() -> None:
    exclude = merged_exclude_set(exclude_large_caps=True)
    assert is_blocked_symbol("NVDA", exclude=exclude)
    assert not is_blocked_symbol("ABCD", exclude=exclude)
