"""Execution adapter (deterministic). Phase 1 migration target for the order parts
of the prototype's `broker.py`.

Rules:
  - Submit Alpaca BRACKET orders only (entry + stop + take-profit atomically).
  - Idempotent: never double-submit for the same intended entry.
  - Honors PAPER_TRADING / ALLOW_LIVE_TRADING flags.
  - No naked entries, no averaging down.

This is the ONLY module (with core/risk) allowed to mutate orders/positions.

NOTE: ``AlpacaBrokerClient`` is intentionally NOT imported here so that importing
this package does not require the alpaca SDK. Import it directly from
``my_trade.core.execution.alpaca_client`` when wiring the live loop.
"""

from .adapter import ExecutionAdapter
from .broker import BrokerClient
from .idempotency import OrderIntent, make_client_order_id
from .models import (
    BrokerError,
    EntryIntent,
    ExecutionMode,
    ExecutionOutcome,
    ExecutionStatus,
    OrderRequest,
    OrderResult,
    OrderStatus,
    OrderType,
    TimeInForce,
    TransientBrokerError,
)
from .planner import build_order_request
from .retry import with_retries

__all__ = [
    "BrokerClient",
    "BrokerError",
    "EntryIntent",
    "ExecutionAdapter",
    "ExecutionMode",
    "ExecutionOutcome",
    "ExecutionStatus",
    "OrderIntent",
    "OrderRequest",
    "OrderResult",
    "OrderStatus",
    "OrderType",
    "TimeInForce",
    "TransientBrokerError",
    "build_order_request",
    "make_client_order_id",
    "with_retries",
]
