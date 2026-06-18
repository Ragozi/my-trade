"""The account boundary (Alpaca Trading API: account + positions).

This is read-only account *state* — distinct from the execution adapter, which
*writes* orders. Both ultimately hit the Trading API, but keeping reads and
writes in separate, narrow Protocols makes each trivially fakeable in tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class Position:
    symbol: str
    qty: float
    avg_entry_price: float
    market_value: float = 0.0
    unrealized_pl: float = 0.0


@dataclass(frozen=True)
class AccountSnapshot:
    """A point-in-time view of the brokerage account."""

    equity: float
    cash: float = 0.0
    last_equity: float = 0.0
    positions: tuple[Position, ...] = field(default_factory=tuple)


@runtime_checkable
class AccountProvider(Protocol):
    def get_snapshot(self) -> AccountSnapshot:
        """Return current equity, cash, and open positions."""
        ...
