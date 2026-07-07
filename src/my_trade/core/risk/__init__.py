"""Risk engine (deterministic). Phase 1 migration target for `risk.py`.

Enforces the hard risk rules from SCOPE.md §7:
  - fixed notional per trade (never scales with conviction/AI score)
  - daily loss limit -> halt new entries
  - max concurrent positions
  - duplicate-entry guard
  - bracket (stop/take-profit) price calculation
  - every entry must ship with a bracket

Prefer pure functions so each rule is trivially unit-testable.
"""

from .engine import (
    atr_stop_price,
    evaluate_trade,
    is_circuit_breaker_tripped,
    is_daily_loss_limit_hit,
    is_daily_profit_target_hit,
    position_size,
)
from .models import (
    AccountState,
    RejectReason,
    RiskDecision,
    RiskLimits,
    SizingResult,
    TradeRequest,
)

__all__ = [
    "AccountState",
    "RejectReason",
    "RiskDecision",
    "RiskLimits",
    "SizingResult",
    "TradeRequest",
    "atr_stop_price",
    "evaluate_trade",
    "is_circuit_breaker_tripped",
    "is_daily_loss_limit_hit",
    "is_daily_profit_target_hit",
    "position_size",
]
