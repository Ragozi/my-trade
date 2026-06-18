"""Pure order construction: EntryIntent + sized qty -> OrderRequest.

No I/O. Validates the long-bracket invariants (stop below entry, take-profit
above entry, positive quantity) and fails closed with ``ValueError`` so the
adapter can reject rather than send a malformed order.
"""

from __future__ import annotations

from .models import EntryIntent, OrderRequest, OrderType, TimeInForce


def build_order_request(
    intent: EntryIntent,
    qty: float,
    client_order_id: str,
    *,
    time_in_force: TimeInForce = TimeInForce.GTC,
) -> OrderRequest:
    """Construct a validated bracket order request for a long entry.

    Raises:
        ValueError: on non-positive qty/prices or an invalid long bracket
            (stop must be below entry, take-profit above entry).
    """
    if qty <= 0:
        raise ValueError(f"qty must be positive, got {qty}")
    if intent.entry_price <= 0 or intent.stop_price <= 0 or intent.take_profit_price <= 0:
        raise ValueError("entry/stop/take-profit prices must all be positive")
    if intent.stop_price >= intent.entry_price:
        raise ValueError(
            f"long stop {intent.stop_price} must be below entry {intent.entry_price}"
        )
    if intent.take_profit_price <= intent.entry_price:
        raise ValueError(
            f"long take-profit {intent.take_profit_price} must be above entry "
            f"{intent.entry_price}"
        )

    limit_price = intent.entry_price if intent.order_type is OrderType.LIMIT else None
    return OrderRequest(
        symbol=intent.symbol,
        side=intent.side,
        qty=qty,
        order_type=intent.order_type,
        client_order_id=client_order_id,
        time_in_force=time_in_force,
        limit_price=limit_price,
        stop_loss_price=intent.stop_price,
        take_profit_price=intent.take_profit_price,
    )
