"""Production ``BrokerClient`` backed by alpaca-py (the I/O boundary).

This is the only execution module that talks to Alpaca. It is intentionally
thin: translate ``OrderRequest`` -> alpaca request, submit, and normalize the
response/exceptions back into our typed contracts. It is exercised by
integration tests (live paper account), not unit tests — the adapter's logic is
unit-tested against the ``BrokerClient`` Protocol with a fake.

alpaca-py picks the paper vs live endpoint from the ``paper`` flag; there is no
base URL to configure (see the alpaca-py crypto examples).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .models import (
    BrokerError,
    ExecutionMode,
    OrderRequest,
    OrderResult,
    OrderStatus,
    OrderType,
    TimeInForce,
    TransientBrokerError,
)

_STATUS_MAP: dict[str, OrderStatus] = {
    "new": OrderStatus.NEW,
    "pending_new": OrderStatus.PENDING,
    "accepted": OrderStatus.ACCEPTED,
    "accepted_for_bidding": OrderStatus.ACCEPTED,
    "partially_filled": OrderStatus.PARTIALLY_FILLED,
    "filled": OrderStatus.FILLED,
    "done_for_day": OrderStatus.ACCEPTED,
    "canceled": OrderStatus.CANCELED,
    "pending_cancel": OrderStatus.ACCEPTED,
    "rejected": OrderStatus.REJECTED,
    "expired": OrderStatus.EXPIRED,
    "replaced": OrderStatus.ACCEPTED,
}

_TRANSIENT_EXCEPTIONS: tuple[type[Exception], ...] = (
    ConnectionError,
    TimeoutError,
    OSError,
)


def _to_status(raw_status: object) -> OrderStatus:
    key = str(getattr(raw_status, "value", raw_status)).lower()
    return _STATUS_MAP.get(key, OrderStatus.UNKNOWN)


def _opt_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


class AlpacaBrokerClient:
    """Adapts alpaca-py's ``TradingClient`` to the ``BrokerClient`` Protocol."""

    def __init__(self, api_key: str, api_secret: str, *, paper: bool = True) -> None:
        from alpaca.trading.client import TradingClient

        self._mode = ExecutionMode.PAPER if paper else ExecutionMode.LIVE
        self._client: Any = TradingClient(api_key=api_key, secret_key=api_secret, paper=paper)

    @property
    def mode(self) -> ExecutionMode:
        return self._mode

    def _build_request(self, request: OrderRequest) -> Any:
        from alpaca.trading.enums import OrderClass, OrderSide
        from alpaca.trading.enums import TimeInForce as AlpacaTIF
        from alpaca.trading.requests import (
            LimitOrderRequest,
            MarketOrderRequest,
            StopLossRequest,
            TakeProfitRequest,
        )

        tif = {
            TimeInForce.GTC: AlpacaTIF.GTC,
            TimeInForce.DAY: AlpacaTIF.DAY,
            TimeInForce.IOC: AlpacaTIF.IOC,
        }[request.time_in_force]
        side = OrderSide.BUY if request.side.value == "buy" else OrderSide.SELL

        bracket: dict[str, Any] = {}
        if request.is_bracket:
            bracket = {
                "order_class": OrderClass.BRACKET,
                "take_profit": TakeProfitRequest(
                    limit_price=round(float(request.take_profit_price or 0.0), 2)
                ),
                "stop_loss": StopLossRequest(
                    stop_price=round(float(request.stop_loss_price or 0.0), 2)
                ),
            }

        if request.order_type is OrderType.LIMIT:
            return LimitOrderRequest(
                symbol=request.symbol,
                qty=request.qty,
                side=side,
                time_in_force=tif,
                limit_price=round(float(request.limit_price or request.qty), 2),
                client_order_id=request.client_order_id,
                **bracket,
            )
        return MarketOrderRequest(
            symbol=request.symbol,
            qty=request.qty,
            side=side,
            time_in_force=tif,
            client_order_id=request.client_order_id,
            **bracket,
        )

    def _map_order(self, order: Any) -> OrderResult:
        return OrderResult(
            client_order_id=str(getattr(order, "client_order_id", "")),
            status=_to_status(getattr(order, "status", None)),
            order_id=str(order.id) if getattr(order, "id", None) is not None else None,
            filled_qty=_opt_float(getattr(order, "filled_qty", 0.0)) or 0.0,
            filled_avg_price=_opt_float(getattr(order, "filled_avg_price", None)),
            submitted_at=datetime.now(UTC),
        )

    def submit_order(self, request: OrderRequest) -> OrderResult:
        from alpaca.common.exceptions import APIError

        try:
            order = self._client.submit_order(self._build_request(request))
        except _TRANSIENT_EXCEPTIONS as exc:
            raise TransientBrokerError(str(exc)) from exc
        except APIError as exc:
            raise BrokerError(str(exc)) from exc
        return self._map_order(order)

    def get_order_by_client_id(self, client_order_id: str) -> OrderResult | None:
        from alpaca.common.exceptions import APIError

        try:
            order = self._client.get_order_by_client_id(client_order_id)
        except _TRANSIENT_EXCEPTIONS as exc:
            raise TransientBrokerError(str(exc)) from exc
        except APIError:
            return None
        if order is None:
            return None
        return self._map_order(order)

    def cancel_order(self, order_id: str) -> None:
        from alpaca.common.exceptions import APIError

        try:
            self._client.cancel_order_by_id(order_id)
        except _TRANSIENT_EXCEPTIONS as exc:
            raise TransientBrokerError(str(exc)) from exc
        except APIError as exc:
            raise BrokerError(str(exc)) from exc

    def close_position(self, symbol: str) -> OrderResult:
        from alpaca.common.exceptions import APIError

        # Alpaca crypto position symbols are unslashed (e.g. BTCUSD).
        alpaca_symbol = symbol.replace("/", "")
        try:
            order = self._client.close_position(alpaca_symbol)
        except _TRANSIENT_EXCEPTIONS as exc:
            raise TransientBrokerError(str(exc)) from exc
        except APIError as exc:
            raise BrokerError(str(exc)) from exc
        return self._map_order(order)

    def list_open_orders(self) -> list[OrderResult]:
        from alpaca.common.exceptions import APIError
        from alpaca.trading.enums import QueryOrderStatus
        from alpaca.trading.requests import GetOrdersRequest

        try:
            orders = self._client.get_orders(
                GetOrdersRequest(status=QueryOrderStatus.OPEN)
            )
        except _TRANSIENT_EXCEPTIONS as exc:
            raise TransientBrokerError(str(exc)) from exc
        except APIError as exc:
            raise BrokerError(str(exc)) from exc
        return [self._map_order(order) for order in orders]
