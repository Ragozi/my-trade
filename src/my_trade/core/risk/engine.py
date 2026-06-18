"""Deterministic risk engine (Phase 1).

Pure functions: inputs -> verdict. No network, no clock, no global state. Any
invalid or ambiguous input fails safe (reject / raise), never sizes up.

Risk limits (SCOPE.md §5b), confirmed by owner for a $12,000 account:
  R1 max risk per trade   = 2%  of current equity
  R2 max total open risk  = 7%  of current equity
  R3 daily loss limit     = 5%  of start-of-day equity
  R4 drawdown breaker     = 15% from peak equity

Evaluation order (first failure wins):
  circuit breaker (R4) -> daily loss (R3) -> max positions ->
  compute size (R1) -> max total open risk (R2) -> approve.
"""

from __future__ import annotations

from .models import (
    AccountState,
    RejectReason,
    RiskDecision,
    RiskLimits,
    SizingResult,
    TradeRequest,
)

# Absolute tolerance for float comparisons on dollar amounts.
_EPS = 1e-9


def position_size(
    equity: float,
    entry_price: float,
    stop_price: float,
    limits: RiskLimits,
) -> SizingResult:
    """Risk-based sizing (R1).

    risk_dollars = equity * limits.max_risk_per_trade_pct
    qty          = risk_dollars / (entry_price - stop_price)   # long

    Raises:
        ValueError: if equity/prices are non-positive or the stop is invalid
            (stop >= entry for a long).
    """
    if equity <= 0:
        raise ValueError(f"equity must be positive, got {equity}")
    if entry_price <= 0 or stop_price <= 0:
        raise ValueError(f"prices must be positive (entry={entry_price}, stop={stop_price})")

    stop_distance = entry_price - stop_price
    if stop_distance <= 0:
        raise ValueError(
            f"invalid long stop: stop {stop_price} must be strictly below entry {entry_price}"
        )

    risk_dollars = equity * limits.max_risk_per_trade_pct
    qty = risk_dollars / stop_distance
    notional = qty * entry_price
    return SizingResult(qty=qty, risk_dollars=risk_dollars, notional=notional)


def atr_stop_price(
    entry_price: float,
    atr: float,
    multiplier: float = 1.5,
) -> float:
    """ATR-aware stop for a long: entry_price - atr * multiplier.

    Raises:
        ValueError: if atr/multiplier is non-positive, or the resulting stop is
            not strictly below entry.
    """
    if atr <= 0:
        raise ValueError(f"atr must be positive, got {atr}")
    if multiplier <= 0:
        raise ValueError(f"multiplier must be positive, got {multiplier}")

    stop = entry_price - atr * multiplier
    if stop >= entry_price or stop <= 0:
        raise ValueError(f"computed stop {stop} is not a valid long stop below {entry_price}")
    return stop


def is_daily_loss_limit_hit(account: AccountState, limits: RiskLimits) -> bool:
    """R3: True when realized day P&L <= -(daily_loss_limit_pct * SOD equity)."""
    threshold = -(limits.daily_loss_limit_pct * account.start_of_day_equity)
    return account.realized_day_pnl <= threshold + _EPS


def is_circuit_breaker_tripped(account: AccountState, limits: RiskLimits) -> bool:
    """R4: True when equity <= (1 - max_drawdown_pct) * peak_equity."""
    floor = (1.0 - limits.max_drawdown_pct) * account.peak_equity
    return account.equity <= floor + _EPS


def evaluate_trade(
    account: AccountState,
    request: TradeRequest,
    limits: RiskLimits,
) -> RiskDecision:
    """Full deterministic verdict for a proposed long entry."""
    # R4 — hard halt takes priority over everything else.
    if is_circuit_breaker_tripped(account, limits):
        return RiskDecision(
            approved=False,
            reason=RejectReason.CIRCUIT_BREAKER,
            detail="max-drawdown circuit breaker tripped; all trading halted",
        )

    # R3 — daily loss limit blocks new entries.
    if is_daily_loss_limit_hit(account, limits):
        return RiskDecision(
            approved=False,
            reason=RejectReason.DAILY_LOSS_LIMIT,
            detail="daily loss limit reached; no new entries today",
        )

    # Position count cap.
    if account.open_positions >= limits.max_concurrent_positions:
        return RiskDecision(
            approved=False,
            reason=RejectReason.MAX_POSITIONS,
            detail=f"open positions {account.open_positions} >= max "
            f"{limits.max_concurrent_positions}",
        )

    # R1 — size the trade; invalid stop is rejected, not raised.
    try:
        sizing = position_size(account.equity, request.entry_price, request.stop_price, limits)
    except ValueError as exc:
        return RiskDecision(approved=False, reason=RejectReason.INVALID_STOP, detail=str(exc))

    if sizing.qty <= 0:
        return RiskDecision(
            approved=False,
            reason=RejectReason.ZERO_QTY,
            detail="computed quantity is zero or negative",
        )

    # R2 — total open risk cap.
    open_risk_cap = limits.max_total_open_risk_pct * account.equity
    projected_open_risk = account.open_risk_dollars + sizing.risk_dollars
    if projected_open_risk > open_risk_cap + _EPS:
        return RiskDecision(
            approved=False,
            reason=RejectReason.MAX_OPEN_RISK,
            sizing=sizing,
            detail=f"projected open risk {projected_open_risk:.2f} exceeds cap "
            f"{open_risk_cap:.2f}",
        )

    return RiskDecision(approved=True, reason=RejectReason.OK, sizing=sizing)
