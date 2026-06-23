"""Post-mortem builder for closed positions (deterministic, no extra LLM call)."""

from __future__ import annotations

from datetime import datetime

from my_trade.research.history import classify_outcome, summarize_reflection
from my_trade.research.models import ClosedTradeReflection


def build_reflection(
    *,
    symbol: str,
    exit_reason: str,
    entry_price: float,
    qty: float,
    unrealized_pl: float,
    thesis_at_entry: str,
    closed_at: datetime,
) -> ClosedTradeReflection:
    """Create a structured reflection from a just-closed position."""
    pnl_estimate = unrealized_pl
    outcome = classify_outcome(exit_reason, pnl_estimate)  # type: ignore[assignment]
    summary = summarize_reflection(
        symbol=symbol,
        outcome=outcome,
        exit_reason=exit_reason,
        pnl_estimate=pnl_estimate,
        thesis_at_entry=thesis_at_entry,
    )
    return ClosedTradeReflection(
        symbol=symbol.upper(),
        closed_at=closed_at,
        outcome=outcome,  # type: ignore[arg-type]
        pnl_estimate=pnl_estimate,
        exit_reason=exit_reason,
        entry_price=entry_price,
        thesis_at_entry=thesis_at_entry,
        summary=summary,
    )
