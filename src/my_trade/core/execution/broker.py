"""The broker boundary the execution adapter depends on.

The adapter depends on this ``Protocol`` rather than on Alpaca directly, so it
is fully unit-testable with a fake. ``AlpacaBrokerClient`` (see
``alpaca_client.py``) is the production implementation.

Implementations should raise ``TransientBrokerError`` for retryable failures
(timeouts, 5xx) and ``BrokerError`` for permanent ones (rejects, auth).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .models import OrderRequest, OrderResult


@runtime_checkable
class BrokerClient(Protocol):
    def submit_order(self, request: OrderRequest) -> OrderResult:
        """Submit an order; return the broker's acknowledgement."""
        ...

    def get_order_by_client_id(self, client_order_id: str) -> OrderResult | None:
        """Look up an order by client order ID (None if not found)."""
        ...

    def cancel_order(self, order_id: str) -> None:
        """Best-effort cancel of a working order."""
        ...

    def list_open_orders(self) -> list[OrderResult]:
        """Return currently working (non-terminal) orders."""
        ...

    def close_position(self, symbol: str) -> OrderResult:
        """Flatten the position in ``symbol`` (cancels related orders first)."""
        ...
