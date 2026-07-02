"""Typed contracts for the execution layer (no I/O, no behavior).

Execution is deliberately *strategy-agnostic*: it consumes a neutral
``EntryIntent`` (prices the strategy proposed) rather than a ``Signal``. The
monitoring loop bridges ``Signal -> EntryIntent``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from my_trade.core.models import OrderSide
from my_trade.core.risk import RiskDecision

if TYPE_CHECKING:
    from my_trade.core.strategy.models import Signal


class OrderType(StrEnum):
    MARKET = "market"
    LIMIT = "limit"


class TimeInForce(StrEnum):
    GTC = "gtc"
    DAY = "day"
    IOC = "ioc"


class OrderStatus(StrEnum):
    NEW = "new"
    PENDING = "pending_new"
    ACCEPTED = "accepted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELED = "canceled"
    REJECTED = "rejected"
    EXPIRED = "expired"
    UNKNOWN = "unknown"

    @property
    def is_terminal(self) -> bool:
        return self in {
            OrderStatus.FILLED,
            OrderStatus.CANCELED,
            OrderStatus.REJECTED,
            OrderStatus.EXPIRED,
        }

    @property
    def is_open(self) -> bool:
        return self in {
            OrderStatus.NEW,
            OrderStatus.PENDING,
            OrderStatus.ACCEPTED,
            OrderStatus.PARTIALLY_FILLED,
        }


class ExecutionMode(StrEnum):
    PAPER = "paper"
    LIVE = "live"


class ExecutionStatus(StrEnum):
    SUBMITTED = "submitted"
    DUPLICATE = "duplicate"
    RISK_REJECTED = "risk_rejected"
    BROKER_ERROR = "broker_error"
    LIVE_BLOCKED = "live_blocked"
    INVALID = "invalid"


class BrokerError(Exception):
    """Non-retryable broker failure (e.g. rejected request, auth error)."""


class TransientBrokerError(BrokerError):
    """Retryable broker failure (timeout, connection reset, 5xx)."""


@dataclass(frozen=True)
class EntryIntent:
    """A broker-agnostic intent to open a long position at proposed prices.

    Prices originate from the strategy; quantity is decided later by the risk
    engine, never here.
    """

    symbol: str
    entry_price: float
    stop_price: float
    take_profit_price: float
    side: OrderSide = OrderSide.BUY
    order_type: OrderType = OrderType.MARKET

    @classmethod
    def from_signal(cls, signal: Signal, order_type: OrderType = OrderType.MARKET) -> EntryIntent:
        return cls(
            symbol=signal.symbol,
            entry_price=signal.entry_price,
            stop_price=signal.stop_price,
            take_profit_price=signal.take_profit_price,
            side=signal.side,
            order_type=order_type,
        )


@dataclass(frozen=True)
class OrderRequest:
    """A fully-specified order ready to send to a broker."""

    symbol: str
    side: OrderSide
    qty: float
    order_type: OrderType
    client_order_id: str
    time_in_force: TimeInForce = TimeInForce.GTC
    limit_price: float | None = None
    stop_loss_price: float | None = None
    take_profit_price: float | None = None

    @property
    def is_bracket(self) -> bool:
        return self.stop_loss_price is not None and self.take_profit_price is not None


@dataclass(frozen=True)
class OrderResult:
    """Normalized view of a broker order across submit/reconcile."""

    client_order_id: str
    status: OrderStatus
    order_id: str | None = None
    symbol: str = ""
    filled_qty: float = 0.0
    filled_avg_price: float | None = None
    submitted_at: datetime | None = None
    message: str = ""

    @property
    def is_filled(self) -> bool:
        return self.status is OrderStatus.FILLED


@dataclass(frozen=True)
class ExecutionOutcome:
    """Result of an ``execute_entry`` call (the deterministic verdict + order)."""

    status: ExecutionStatus
    client_order_id: str
    submitted: bool = False
    order: OrderResult | None = None
    risk_decision: RiskDecision | None = None
    detail: str = ""
