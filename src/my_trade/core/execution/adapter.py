"""ExecutionAdapter: the only component that turns an intent into a live order.

Safe path (fail-closed at every step):
  1. Build a deterministic client order ID (idempotency).
  2. Reconcile: if a non-rejected order already exists for that ID -> DUPLICATE.
  3. Risk gate: ``evaluate_trade`` must approve; quantity comes from the risk
     engine's sizing. If not approved -> RISK_REJECTED, no order is sent.
  4. Plan a validated bracket order.
  5. Submit through the broker with bounded retries (safe due to the stable ID).

The adapter never sizes positions or invents limits — that is the risk engine's
job. It never imports the research layer, and the research layer can never
import it (enforced by the architecture guardrail test).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime

from my_trade.core.risk import (
    AccountState,
    RiskLimits,
    TradeRequest,
    evaluate_trade,
)

from my_trade.data import normalize_symbol

from .broker import BrokerClient
from .idempotency import OrderIntent, make_client_order_id
from .models import (
    BrokerError,
    EntryIntent,
    ExecutionMode,
    ExecutionOutcome,
    ExecutionStatus,
    OrderResult,
    OrderStatus,
    TimeInForce,
)
from .planner import build_order_request
from .retry import with_retries


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ExecutionAdapter:
    """Coordinates idempotency, risk gating, planning, and submission."""

    def __init__(
        self,
        broker: BrokerClient,
        limits: RiskLimits,
        *,
        mode: ExecutionMode = ExecutionMode.PAPER,
        allow_live: bool = False,
        max_submit_attempts: int = 3,
        whole_shares: bool = False,
        default_time_in_force: TimeInForce = TimeInForce.GTC,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        if mode is ExecutionMode.LIVE and not allow_live:
            raise ValueError(
                "Refusing to create a LIVE execution adapter without allow_live=True"
            )
        self._broker = broker
        self._limits = limits
        self._mode = mode
        self._attempts = max_submit_attempts
        self._whole_shares = whole_shares
        self._default_tif = default_time_in_force
        self._sleep = sleep
        self._clock = clock

    @property
    def mode(self) -> ExecutionMode:
        return self._mode

    def execute_entry(
        self,
        intent: EntryIntent,
        account: AccountState,
        *,
        now: datetime | None = None,
        time_in_force: TimeInForce | None = None,
    ) -> ExecutionOutcome:
        """Run the full safe path for a proposed long entry."""
        when = now or self._clock()
        tif = time_in_force or self._default_tif
        client_order_id = make_client_order_id(intent.symbol, OrderIntent.ENTRY, when)

        # (2) Idempotency / reconciliation: don't resubmit an existing order.
        existing = self._broker.get_order_by_client_id(client_order_id)
        if existing is not None and existing.status is not OrderStatus.REJECTED:
            return ExecutionOutcome(
                status=ExecutionStatus.DUPLICATE,
                client_order_id=client_order_id,
                submitted=False,
                order=existing,
                detail="order already exists for this client_order_id",
            )

        # (3) Risk gate — fail-closed. Sizing comes from the risk engine.
        decision = evaluate_trade(
            account,
            TradeRequest(
                symbol=intent.symbol,
                entry_price=intent.entry_price,
                stop_price=intent.stop_price,
            ),
            self._limits,
        )
        if not decision.approved or decision.sizing is None:
            return ExecutionOutcome(
                status=ExecutionStatus.RISK_REJECTED,
                client_order_id=client_order_id,
                submitted=False,
                risk_decision=decision,
                detail=f"risk rejected: {decision.reason.value}",
            )

        # Equities can't bracket fractional shares: floor to whole shares and
        # reject (fail-closed) when the risk-sized quantity rounds to zero.
        qty = decision.sizing.qty
        if self._whole_shares:
            qty = float(int(qty))
            if qty < 1:
                return ExecutionOutcome(
                    status=ExecutionStatus.INVALID,
                    client_order_id=client_order_id,
                    submitted=False,
                    risk_decision=decision,
                    detail="risk-sized quantity rounds to 0 whole shares",
                )

        # (4) Plan a validated bracket order.
        try:
            request = build_order_request(
                intent,
                qty,
                client_order_id,
                time_in_force=tif,
            )
        except ValueError as exc:
            return ExecutionOutcome(
                status=ExecutionStatus.INVALID,
                client_order_id=client_order_id,
                submitted=False,
                risk_decision=decision,
                detail=str(exc),
            )

        # (5) Submit with bounded retries (idempotent via client_order_id).
        try:
            result: OrderResult = with_retries(
                lambda: self._broker.submit_order(request),
                attempts=self._attempts,
                sleep=self._sleep,
            )
        except BrokerError as exc:
            return ExecutionOutcome(
                status=ExecutionStatus.BROKER_ERROR,
                client_order_id=client_order_id,
                submitted=False,
                risk_decision=decision,
                detail=f"broker error after retries: {exc}",
            )

        return ExecutionOutcome(
            status=ExecutionStatus.SUBMITTED,
            client_order_id=client_order_id,
            submitted=True,
            order=result,
            risk_decision=decision,
        )

    def close_position(self, symbol: str, *, now: datetime | None = None) -> ExecutionOutcome:
        """Flatten an open position (used by the orchestrator for soft exits).

        Bracket stop/take-profit legs live at the broker; cancel them first so
        shares are not ``held_for_orders`` when we submit a discretionary exit.
        """
        when = now or self._clock()
        client_order_id = make_client_order_id(symbol, OrderIntent.EXIT, when)
        self._cancel_open_orders_for_symbol(symbol)
        try:
            result: OrderResult = with_retries(
                lambda: self._broker.close_position(symbol),
                attempts=self._attempts,
                sleep=self._sleep,
            )
        except BrokerError as exc:
            return ExecutionOutcome(
                status=ExecutionStatus.BROKER_ERROR,
                client_order_id=client_order_id,
                submitted=False,
                detail=f"close failed after retries: {exc}",
            )
        return ExecutionOutcome(
            status=ExecutionStatus.SUBMITTED,
            client_order_id=client_order_id,
            submitted=True,
            order=result,
        )

    def _cancel_open_orders_for_symbol(self, symbol: str) -> None:
        """Best-effort cancel of working orders that block a market close."""
        target = normalize_symbol(symbol)
        try:
            open_orders = self._broker.list_open_orders()
        except BrokerError:
            return
        for order in open_orders:
            if not order.order_id:
                continue
            order_sym = normalize_symbol(order.symbol) if order.symbol else ""
            if order_sym != target:
                continue
            try:
                self._broker.cancel_order(order.order_id)
            except BrokerError:
                continue

    def reconcile(self, client_order_id: str) -> OrderResult | None:
        """Fetch the current broker state for a previously-submitted order."""
        return self._broker.get_order_by_client_id(client_order_id)
