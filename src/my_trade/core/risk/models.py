"""Typed contracts for the deterministic risk engine.

These are plain data holders (no behavior, no I/O) so they are trivial to
construct in tests. All limits are expressed as fractions of equity (e.g. 0.02
== 2%) and evaluated against *live* equity unless noted otherwise.

See SCOPE.md §5b (risk limits R1–R4) and §7 (hard risk rules).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


@dataclass(frozen=True)
class RiskLimits:
    """The four core risk dials plus position count (SCOPE.md §5b)."""

    max_risk_per_trade_pct: float = 0.02   # R1
    max_total_open_risk_pct: float = 0.07  # R2
    daily_loss_limit_pct: float = 0.05     # R3
    daily_profit_target_pct: float = 0.0   # halt new entries when day P&L >= this × SOD (0=off)
    max_drawdown_pct: float = 0.15         # R4
    max_concurrent_positions: int = 1
    max_notional_pct: float = 0.25  # max position value as fraction of equity


@dataclass(frozen=True)
class AccountState:
    """Snapshot of the account at decision time.

    open_risk_dollars = sum over open positions of (entry - stop) * qty.
    realized_day_pnl is negative for a losing day.
    """

    equity: float
    start_of_day_equity: float
    peak_equity: float
    realized_day_pnl: float
    open_positions: int
    open_risk_dollars: float


@dataclass(frozen=True)
class TradeRequest:
    """A proposed long entry awaiting risk approval.

    `atr` is optional and only used by the ATR-aware helpers.
    """

    symbol: str
    entry_price: float
    stop_price: float
    atr: float | None = None


@dataclass(frozen=True)
class SizingResult:
    """Output of risk-based position sizing."""

    qty: float
    risk_dollars: float
    notional: float


class RejectReason(StrEnum):
    OK = "ok"
    CIRCUIT_BREAKER = "circuit_breaker"      # R4
    DAILY_LOSS_LIMIT = "daily_loss_limit"    # R3
    MAX_POSITIONS = "max_positions"
    MAX_OPEN_RISK = "max_open_risk"          # R2
    INVALID_STOP = "invalid_stop"
    ZERO_QTY = "zero_qty"


@dataclass(frozen=True)
class RiskDecision:
    """Final approve/reject verdict from the risk engine."""

    approved: bool
    reason: RejectReason
    sizing: SizingResult | None = None
    detail: str = ""
