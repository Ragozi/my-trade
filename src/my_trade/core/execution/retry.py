"""Bounded retry helper for transient broker failures.

The sleep function is injectable so tests run instantly and deterministically.
Retries are only safe because submissions carry a stable client order ID
(see ``idempotency.py``) — a retried submit cannot create a duplicate order.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar

from .models import TransientBrokerError

T = TypeVar("T")


def with_retries(
    operation: Callable[[], T],
    *,
    attempts: int = 3,
    retryable: tuple[type[Exception], ...] = (TransientBrokerError,),
    sleep: Callable[[float], None] = time.sleep,
    backoff_seconds: float = 0.5,
) -> T:
    """Call ``operation`` up to ``attempts`` times, retrying only ``retryable``.

    Raises the last exception if all attempts fail. Non-retryable exceptions
    propagate immediately.
    """
    if attempts < 1:
        raise ValueError("attempts must be >= 1")

    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except retryable as exc:
            last_error = exc
            if attempt >= attempts:
                break
            sleep(backoff_seconds * attempt)

    assert last_error is not None  # only reachable after a retryable failure
    raise last_error
