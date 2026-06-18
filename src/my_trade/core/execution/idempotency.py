"""Deterministic client order IDs for duplicate prevention.

A client order ID is derived purely from (symbol, intent, time-bucket), so two
scans within the same minute produce the *same* ID. Combined with the broker's
uniqueness guarantee, this prevents duplicate entries across retries and process
restarts without any shared mutable state.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from my_trade.data import normalize_symbol


class OrderIntent(StrEnum):
    ENTRY = "entry"
    EXIT = "exit"


def make_client_order_id(
    symbol: str,
    intent: OrderIntent,
    when: datetime,
    *,
    prefix: str = "mt",
) -> str:
    """Build a stable client order ID, bucketed to the minute.

    Example: ``mt-entry-BTCUSD-20260618T1407``.
    """
    bucket = when.strftime("%Y%m%dT%H%M")
    return f"{prefix}-{intent.value}-{normalize_symbol(symbol)}-{bucket}"
