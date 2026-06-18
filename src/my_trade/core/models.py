"""Shared deterministic-core contracts used across multiple core layers.

Keep this module tiny and dependency-free so any core layer (strategy,
execution, risk, monitoring) can import it without creating cycles.
"""

from __future__ import annotations

from enum import StrEnum


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"
