"""Tests for the execution layer (pure parts + adapter against a fake broker)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from my_trade.core.execution import (
    BrokerError,
    EntryIntent,
    ExecutionAdapter,
    ExecutionMode,
    ExecutionStatus,
    OrderIntent,
    OrderRequest,
    OrderResult,
    OrderStatus,
    OrderType,
    TransientBrokerError,
    build_order_request,
    make_client_order_id,
    with_retries,
)
from my_trade.core.models import OrderSide
from my_trade.core.risk import AccountState, RiskLimits

NOW = datetime(2026, 6, 18, 14, 7, tzinfo=UTC)
ENTRY = 100_000.0
STOP = 99_350.0          # $650 below -> risk sizing $240 / 650
TAKE_PROFIT = 101_700.0


def limits(**overrides: float | int) -> RiskLimits:
    base: dict[str, float | int] = {
        "max_risk_per_trade_pct": 0.02,
        "max_total_open_risk_pct": 0.07,
        "daily_loss_limit_pct": 0.05,
        "max_drawdown_pct": 0.15,
        "max_concurrent_positions": 1,
    }
    base.update(overrides)
    return RiskLimits(**base)  # type: ignore[arg-type]


def account(**overrides: float | int) -> AccountState:
    base: dict[str, float | int] = {
        "equity": 12_000.0,
        "start_of_day_equity": 12_000.0,
        "peak_equity": 12_000.0,
        "realized_day_pnl": 0.0,
        "open_positions": 0,
        "open_risk_dollars": 0.0,
    }
    base.update(overrides)
    return AccountState(**base)  # type: ignore[arg-type]


def intent(**overrides: object) -> EntryIntent:
    base: dict[str, object] = {
        "symbol": "BTC/USD",
        "entry_price": ENTRY,
        "stop_price": STOP,
        "take_profit_price": TAKE_PROFIT,
    }
    base.update(overrides)
    return EntryIntent(**base)  # type: ignore[arg-type]


class FakeBroker:
    """In-memory BrokerClient for deterministic adapter tests."""

    def __init__(
        self,
        *,
        transient_failures: int = 0,
        permanent_error: bool = False,
        existing: dict[str, OrderResult] | None = None,
        open_orders: list[OrderResult] | None = None,
    ) -> None:
        self.submitted: list[OrderRequest] = []
        self.submit_calls = 0
        self.cancelled: list[str] = []
        self.closed: list[str] = []
        self._transient_failures = transient_failures
        self._permanent_error = permanent_error
        self._existing = existing or {}
        self._open_orders = list(open_orders or [])

    def submit_order(self, request: OrderRequest) -> OrderResult:
        self.submit_calls += 1
        if self._transient_failures > 0:
            self._transient_failures -= 1
            raise TransientBrokerError("simulated timeout")
        if self._permanent_error:
            raise BrokerError("simulated reject")
        self.submitted.append(request)
        return OrderResult(
            client_order_id=request.client_order_id,
            status=OrderStatus.ACCEPTED,
            order_id="sim-order-1",
        )

    def get_order_by_client_id(self, client_order_id: str) -> OrderResult | None:
        return self._existing.get(client_order_id)

    def cancel_order(self, order_id: str) -> None:
        self.cancelled.append(order_id)
        self._open_orders = [o for o in self._open_orders if o.order_id != order_id]

    def list_open_orders(self) -> list[OrderResult]:
        return list(self._open_orders)

    def close_position(self, symbol: str) -> OrderResult:
        self.closed.append(symbol)
        if self._permanent_error:
            raise BrokerError("simulated close reject")
        return OrderResult(
            client_order_id=f"close-{symbol}",
            status=OrderStatus.FILLED,
            order_id="sim-close-1",
        )


def make_adapter(broker: FakeBroker, **kwargs: object) -> ExecutionAdapter:
    return ExecutionAdapter(
        broker,
        limits(),
        sleep=lambda _seconds: None,  # no real sleeping in tests
        **kwargs,  # type: ignore[arg-type]
    )


# --------------------------------------------------------------------------- #
# Idempotency
# --------------------------------------------------------------------------- #
class TestIdempotency:
    def test_client_order_id_is_deterministic(self) -> None:
        a = make_client_order_id("BTC/USD", OrderIntent.ENTRY, NOW)
        b = make_client_order_id("btcusd", OrderIntent.ENTRY, NOW)
        assert a == b == "mt-entry-BTCUSD-20260618T1407"

    def test_client_order_id_changes_with_minute(self) -> None:
        later = NOW.replace(minute=8)
        assert make_client_order_id("BTC/USD", OrderIntent.ENTRY, NOW) != make_client_order_id(
            "BTC/USD", OrderIntent.ENTRY, later
        )


# --------------------------------------------------------------------------- #
# Planner
# --------------------------------------------------------------------------- #
class TestPlanner:
    def test_builds_bracket_market_order(self) -> None:
        req = build_order_request(intent(), qty=0.5, client_order_id="cid")
        assert req.is_bracket
        assert req.stop_loss_price == STOP
        assert req.take_profit_price == TAKE_PROFIT
        assert req.order_type is OrderType.MARKET
        assert req.limit_price is None
        assert req.side is OrderSide.BUY

    def test_limit_order_sets_limit_price(self) -> None:
        req = build_order_request(
            intent(order_type=OrderType.LIMIT), qty=0.5, client_order_id="cid"
        )
        assert req.limit_price == ENTRY

    def test_rejects_non_positive_qty(self) -> None:
        with pytest.raises(ValueError):
            build_order_request(intent(), qty=0.0, client_order_id="cid")

    def test_rejects_stop_at_or_above_entry(self) -> None:
        with pytest.raises(ValueError):
            build_order_request(intent(stop_price=ENTRY), qty=0.5, client_order_id="cid")

    def test_rejects_take_profit_below_entry(self) -> None:
        with pytest.raises(ValueError):
            build_order_request(
                intent(take_profit_price=ENTRY - 1), qty=0.5, client_order_id="cid"
            )


# --------------------------------------------------------------------------- #
# Retry helper
# --------------------------------------------------------------------------- #
class TestRetries:
    def test_succeeds_after_transient_failures(self) -> None:
        calls = {"n": 0}

        def op() -> str:
            calls["n"] += 1
            if calls["n"] < 3:
                raise TransientBrokerError("boom")
            return "ok"

        assert with_retries(op, attempts=3, sleep=lambda _s: None) == "ok"
        assert calls["n"] == 3

    def test_raises_after_exhausting_attempts(self) -> None:
        def op() -> str:
            raise TransientBrokerError("always")

        with pytest.raises(TransientBrokerError):
            with_retries(op, attempts=3, sleep=lambda _s: None)

    def test_non_retryable_propagates_immediately(self) -> None:
        calls = {"n": 0}

        def op() -> str:
            calls["n"] += 1
            raise BrokerError("permanent")

        with pytest.raises(BrokerError):
            with_retries(op, attempts=3, sleep=lambda _s: None)
        assert calls["n"] == 1

    def test_invalid_attempts_raises(self) -> None:
        with pytest.raises(ValueError):
            with_retries(lambda: 1, attempts=0)


# --------------------------------------------------------------------------- #
# Live-mode guard
# --------------------------------------------------------------------------- #
class TestLiveGuard:
    def test_live_without_allow_raises(self) -> None:
        with pytest.raises(ValueError):
            ExecutionAdapter(FakeBroker(), limits(), mode=ExecutionMode.LIVE)

    def test_live_with_allow_is_permitted(self) -> None:
        adapter = ExecutionAdapter(
            FakeBroker(), limits(), mode=ExecutionMode.LIVE, allow_live=True
        )
        assert adapter.mode is ExecutionMode.LIVE

    def test_default_mode_is_paper(self) -> None:
        assert make_adapter(FakeBroker()).mode is ExecutionMode.PAPER


# --------------------------------------------------------------------------- #
# Adapter: full safe path
# --------------------------------------------------------------------------- #
class TestExecuteEntry:
    def test_happy_path_submits_with_risk_sizing(self) -> None:
        broker = FakeBroker()
        adapter = make_adapter(broker)
        outcome = adapter.execute_entry(intent(), account(), now=NOW)

        assert outcome.status is ExecutionStatus.SUBMITTED
        assert outcome.submitted is True
        assert outcome.order is not None
        assert outcome.client_order_id == "mt-entry-BTCUSD-20260618T1407"
        assert broker.submit_calls == 1
        sent = broker.submitted[0]
        assert sent.is_bracket
        assert sent.client_order_id == outcome.client_order_id
        # qty sized by the risk engine: $240 risk / $650 stop distance.
        assert sent.qty == pytest.approx(240.0 / 650.0)

    def test_circuit_breaker_blocks_submission(self) -> None:
        broker = FakeBroker()
        adapter = make_adapter(broker)
        acct = account(peak_equity=12_000.0, equity=9_000.0)  # >15% drawdown
        outcome = adapter.execute_entry(intent(), acct, now=NOW)
        assert outcome.status is ExecutionStatus.RISK_REJECTED
        assert outcome.submitted is False
        assert broker.submit_calls == 0

    def test_daily_loss_blocks_submission(self) -> None:
        broker = FakeBroker()
        outcome = make_adapter(broker).execute_entry(
            intent(), account(realized_day_pnl=-600.0), now=NOW
        )
        assert outcome.status is ExecutionStatus.RISK_REJECTED
        assert broker.submit_calls == 0

    def test_max_positions_blocks_submission(self) -> None:
        broker = FakeBroker()
        outcome = make_adapter(broker).execute_entry(
            intent(), account(open_positions=1), now=NOW
        )
        assert outcome.status is ExecutionStatus.RISK_REJECTED
        assert broker.submit_calls == 0

    def test_duplicate_order_is_not_resubmitted(self) -> None:
        cid = make_client_order_id("BTC/USD", OrderIntent.ENTRY, NOW)
        existing = {cid: OrderResult(client_order_id=cid, status=OrderStatus.ACCEPTED)}
        broker = FakeBroker(existing=existing)
        outcome = make_adapter(broker).execute_entry(intent(), account(), now=NOW)
        assert outcome.status is ExecutionStatus.DUPLICATE
        assert outcome.submitted is False
        assert broker.submit_calls == 0

    def test_previously_rejected_order_allows_resubmit(self) -> None:
        cid = make_client_order_id("BTC/USD", OrderIntent.ENTRY, NOW)
        existing = {cid: OrderResult(client_order_id=cid, status=OrderStatus.REJECTED)}
        broker = FakeBroker(existing=existing)
        outcome = make_adapter(broker).execute_entry(intent(), account(), now=NOW)
        assert outcome.status is ExecutionStatus.SUBMITTED
        assert broker.submit_calls == 1

    def test_invalid_bracket_passes_risk_but_fails_planner(self) -> None:
        # take_profit <= entry passes the risk gate (which only checks the stop)
        # but the planner rejects it -> INVALID, nothing submitted.
        broker = FakeBroker()
        bad = intent(take_profit_price=ENTRY - 100.0)
        outcome = make_adapter(broker).execute_entry(bad, account(), now=NOW)
        assert outcome.status is ExecutionStatus.INVALID
        assert broker.submit_calls == 0

    def test_retries_then_succeeds(self) -> None:
        broker = FakeBroker(transient_failures=2)
        adapter = make_adapter(broker, max_submit_attempts=3)
        outcome = adapter.execute_entry(intent(), account(), now=NOW)
        assert outcome.status is ExecutionStatus.SUBMITTED
        assert broker.submit_calls == 3

    def test_retries_exhausted_returns_broker_error(self) -> None:
        broker = FakeBroker(transient_failures=5)
        adapter = make_adapter(broker, max_submit_attempts=3)
        outcome = adapter.execute_entry(intent(), account(), now=NOW)
        assert outcome.status is ExecutionStatus.BROKER_ERROR
        assert outcome.submitted is False
        assert broker.submit_calls == 3

    def test_permanent_broker_error_not_retried(self) -> None:
        broker = FakeBroker(permanent_error=True)
        adapter = make_adapter(broker, max_submit_attempts=3)
        outcome = adapter.execute_entry(intent(), account(), now=NOW)
        assert outcome.status is ExecutionStatus.BROKER_ERROR
        assert broker.submit_calls == 1

    def test_close_position_submits(self) -> None:
        broker = FakeBroker()
        outcome = make_adapter(broker).close_position("BTC/USD", now=NOW)
        assert outcome.status is ExecutionStatus.SUBMITTED
        assert outcome.submitted is True
        assert broker.closed == ["BTC/USD"]
        assert outcome.order is not None and outcome.order.is_filled

    def test_close_position_broker_error(self) -> None:
        broker = FakeBroker(permanent_error=True)
        outcome = make_adapter(broker).close_position("BTC/USD", now=NOW)
        assert outcome.status is ExecutionStatus.BROKER_ERROR
        assert outcome.submitted is False

    def test_close_position_cancels_open_orders_first(self) -> None:
        broker = FakeBroker(
            open_orders=[
                OrderResult(
                    client_order_id="bracket-stop",
                    status=OrderStatus.ACCEPTED,
                    order_id="stop-1",
                    symbol="MSFT",
                ),
                OrderResult(
                    client_order_id="other-symbol",
                    status=OrderStatus.ACCEPTED,
                    order_id="tp-9",
                    symbol="AAPL",
                ),
            ]
        )
        outcome = make_adapter(broker).close_position("MSFT", now=NOW)
        assert outcome.status is ExecutionStatus.SUBMITTED
        assert broker.cancelled == ["stop-1"]
        assert broker.closed == ["MSFT"]

    def test_reconcile_returns_existing(self) -> None:
        cid = "mt-entry-BTCUSD-20260618T1407"
        existing = {cid: OrderResult(client_order_id=cid, status=OrderStatus.FILLED)}
        adapter = make_adapter(FakeBroker(existing=existing))
        result = adapter.reconcile(cid)
        assert result is not None
        assert result.is_filled


# --------------------------------------------------------------------------- #
# Equities support: whole-share rounding + default time-in-force
# --------------------------------------------------------------------------- #
class TestEquitiesExecution:
    def _equity_intent(self) -> EntryIntent:
        # entry 100, stop 99 => $1 risk/share; $240 budget => 240 whole shares.
        return intent(
            symbol="AAPL", entry_price=100.0, stop_price=99.0, take_profit_price=103.0
        )

    def test_whole_shares_floors_quantity(self) -> None:
        broker = FakeBroker()
        adapter = make_adapter(broker, whole_shares=True)
        outcome = adapter.execute_entry(self._equity_intent(), account(), now=NOW)
        assert outcome.status is ExecutionStatus.SUBMITTED
        assert broker.submitted[0].qty == 240.0  # floored to whole shares

    def test_whole_shares_rounding_to_zero_is_invalid(self) -> None:
        # $240 risk budget / $650 stop distance => 0.369 shares -> floors to 0.
        broker = FakeBroker()
        adapter = make_adapter(broker, whole_shares=True)
        outcome = adapter.execute_entry(intent(), account(), now=NOW)
        assert outcome.status is ExecutionStatus.INVALID
        assert broker.submit_calls == 0

    def test_default_time_in_force_applied(self) -> None:
        from my_trade.core.execution import TimeInForce

        broker = FakeBroker()
        adapter = make_adapter(
            broker, whole_shares=True, default_time_in_force=TimeInForce.DAY
        )
        adapter.execute_entry(self._equity_intent(), account(), now=NOW)
        assert broker.submitted[0].time_in_force is TimeInForce.DAY

    def test_crypto_keeps_fractional_and_gtc(self) -> None:
        from my_trade.core.execution import TimeInForce

        broker = FakeBroker()
        outcome = make_adapter(broker).execute_entry(intent(), account(), now=NOW)
        assert outcome.status is ExecutionStatus.SUBMITTED
        assert broker.submitted[0].qty == pytest.approx(240.0 / 650.0)
        assert broker.submitted[0].time_in_force is TimeInForce.GTC


# --------------------------------------------------------------------------- #
# Misc model behavior
# --------------------------------------------------------------------------- #
class TestModels:
    def test_protocol_is_satisfied_by_fake(self) -> None:
        from my_trade.core.execution import BrokerClient

        assert isinstance(FakeBroker(), BrokerClient)

    def test_order_status_terminal_and_open(self) -> None:
        assert OrderStatus.FILLED.is_terminal is True
        assert OrderStatus.ACCEPTED.is_open is True
        assert OrderStatus.FILLED.is_open is False

    def test_entry_intent_from_signal(self) -> None:
        from my_trade.core.strategy import OrderSide as StratSide
        from my_trade.core.strategy import Signal

        sig = Signal(
            symbol="BTC/USD",
            side=StratSide.BUY,
            entry_price=ENTRY,
            stop_price=STOP,
            take_profit_price=TAKE_PROFIT,
            confidence=0.5,
        )
        built = EntryIntent.from_signal(sig)
        assert built.symbol == "BTC/USD"
        assert built.entry_price == ENTRY
        assert built.side is OrderSide.BUY
