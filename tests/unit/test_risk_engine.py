"""Behavior spec for the deterministic risk engine.

These were written test-first (TDD); the engine is now implemented and they must
pass for real. All numbers assume the conservative $12,000 defaults from
SCOPE.md §5b:
  R1 max risk/trade   = 2%  -> $240
  R2 max open risk    = 7%  -> $840
  R3 daily loss limit = 5%  -> $600
  R4 circuit breaker  = 15% from peak -> halt at $10,200
"""

from __future__ import annotations

import math

import pytest

from my_trade.core.risk import (
    AccountState,
    RejectReason,
    RiskLimits,
    TradeRequest,
    atr_stop_price,
    evaluate_trade,
    is_circuit_breaker_tripped,
    is_daily_loss_limit_hit,
    position_size,
)

EQUITY = 12_000.0
ENTRY = 100_000.0
STOP = 99_350.0  # 0.65% below entry -> $650 stop distance


def default_limits() -> RiskLimits:
    return RiskLimits(
        max_risk_per_trade_pct=0.02,
        max_total_open_risk_pct=0.07,
        daily_loss_limit_pct=0.05,
        max_drawdown_pct=0.15,
        max_concurrent_positions=1,
        max_notional_pct=0.25,
    )


def healthy_account(**overrides: float | int) -> AccountState:
    base: dict[str, float | int] = {
        "equity": EQUITY,
        "start_of_day_equity": EQUITY,
        "peak_equity": EQUITY,
        "realized_day_pnl": 0.0,
        "open_positions": 0,
        "open_risk_dollars": 0.0,
    }
    base.update(overrides)
    return AccountState(**base)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# R1 — risk-based position sizing
# --------------------------------------------------------------------------- #
class TestPositionSizing:
    def test_notional_capped_at_max_notional_pct(self) -> None:
        """Tight stops must not exceed max_notional_pct of equity (NVDA-class bug)."""
        entry = 192.0
        stop = entry * (1 - 0.0065)
        s = position_size(15_000.0, entry, stop, default_limits())
        assert s.notional <= 15_000.0 * 0.25 + 1e-6
        assert s.qty == pytest.approx((15_000.0 * 0.25) / entry)

    def test_risk_dollars_is_two_percent_when_not_capped(self) -> None:
        entry = 50.0
        stop = 45.0  # wide enough stop that 25% notional cap is not binding
        s = position_size(EQUITY, entry, stop, default_limits())
        assert s.risk_dollars == pytest.approx(240.0)

    def test_qty_makes_stop_loss_equal_risk_budget_when_not_capped(self) -> None:
        entry = 50.0
        stop = 45.0
        s = position_size(EQUITY, entry, stop, default_limits())
        assert (entry - stop) * s.qty == pytest.approx(240.0)

    def test_high_price_entry_is_notional_capped(self) -> None:
        s = position_size(EQUITY, ENTRY, STOP, default_limits())
        assert s.notional == pytest.approx(EQUITY * 0.25)
        assert s.qty == pytest.approx((EQUITY * 0.25) / ENTRY)

    def test_invalid_stop_at_or_above_entry_raises(self) -> None:
        with pytest.raises(ValueError):
            position_size(EQUITY, ENTRY, ENTRY, default_limits())
        with pytest.raises(ValueError):
            position_size(EQUITY, ENTRY, ENTRY + 1, default_limits())

    def test_sizing_scales_with_current_equity(self) -> None:
        # Half the equity -> half the risk budget -> half the size.
        full = position_size(EQUITY, ENTRY, STOP, default_limits())
        half = position_size(EQUITY / 2, ENTRY, STOP, default_limits())
        assert half.qty == pytest.approx(full.qty / 2)

    def test_non_positive_equity_raises(self) -> None:
        with pytest.raises(ValueError):
            position_size(0.0, ENTRY, STOP, default_limits())

    def test_non_positive_prices_raise(self) -> None:
        with pytest.raises(ValueError):
            position_size(EQUITY, -1.0, STOP, default_limits())
        with pytest.raises(ValueError):
            position_size(EQUITY, ENTRY, 0.0, default_limits())


# --------------------------------------------------------------------------- #
# ATR-aware stop helper
# --------------------------------------------------------------------------- #
class TestAtrStop:
    def test_atr_stop_is_entry_minus_atr_times_multiplier(self) -> None:
        assert atr_stop_price(100_000.0, atr=500.0, multiplier=1.5) == pytest.approx(99_250.0)

    def test_atr_derived_stop_feeds_sizing(self) -> None:
        stop = atr_stop_price(ENTRY, atr=500.0, multiplier=1.5)  # 99_250 -> $750 dist
        s = position_size(EQUITY, ENTRY, stop, default_limits())
        assert s.notional == pytest.approx(EQUITY * 0.25)
        assert s.qty == pytest.approx((EQUITY * 0.25) / ENTRY)

    def test_non_positive_atr_raises(self) -> None:
        with pytest.raises(ValueError):
            atr_stop_price(ENTRY, atr=0.0, multiplier=1.5)

    def test_non_positive_multiplier_raises(self) -> None:
        with pytest.raises(ValueError):
            atr_stop_price(ENTRY, atr=500.0, multiplier=0.0)

    def test_atr_wider_than_entry_raises(self) -> None:
        # An ATR-derived stop that would land at/below zero is invalid.
        with pytest.raises(ValueError):
            atr_stop_price(100.0, atr=100.0, multiplier=1.5)


# --------------------------------------------------------------------------- #
# R3 — daily loss limit
# --------------------------------------------------------------------------- #
class TestDailyLossLimit:
    def test_not_hit_just_above_threshold(self) -> None:
        acct = healthy_account(realized_day_pnl=-599.99)
        assert is_daily_loss_limit_hit(acct, default_limits()) is False

    def test_hit_exactly_at_threshold(self) -> None:
        acct = healthy_account(realized_day_pnl=-600.0)
        assert is_daily_loss_limit_hit(acct, default_limits()) is True

    def test_hit_below_threshold(self) -> None:
        acct = healthy_account(realized_day_pnl=-750.0)
        assert is_daily_loss_limit_hit(acct, default_limits()) is True

    def test_uses_start_of_day_equity_not_current(self) -> None:
        # SOD equity 12_000 -> threshold -600 regardless of intraday equity.
        acct = healthy_account(equity=9_000.0, realized_day_pnl=-600.0)
        assert is_daily_loss_limit_hit(acct, default_limits()) is True


# --------------------------------------------------------------------------- #
# R4 — max-drawdown circuit breaker
# --------------------------------------------------------------------------- #
class TestCircuitBreaker:
    def test_not_tripped_above_threshold(self) -> None:
        acct = healthy_account(peak_equity=12_000.0, equity=10_201.0)
        assert is_circuit_breaker_tripped(acct, default_limits()) is False

    def test_tripped_exactly_at_threshold(self) -> None:
        acct = healthy_account(peak_equity=12_000.0, equity=10_200.0)  # -15%
        assert is_circuit_breaker_tripped(acct, default_limits()) is True

    def test_tripped_below_threshold(self) -> None:
        acct = healthy_account(peak_equity=12_000.0, equity=9_000.0)
        assert is_circuit_breaker_tripped(acct, default_limits()) is True


# --------------------------------------------------------------------------- #
# evaluate_trade — full verdict + ordering + R2 open-risk cap + positions
# --------------------------------------------------------------------------- #
class TestEvaluateTrade:
    def test_happy_path_approves_with_sizing(self) -> None:
        req = TradeRequest("BTC/USD", 50.0, 45.0)
        d = evaluate_trade(healthy_account(), req, default_limits())
        assert d.approved is True
        assert d.reason is RejectReason.OK
        assert d.sizing is not None
        assert d.sizing.risk_dollars == pytest.approx(240.0)

    def test_circuit_breaker_takes_priority(self) -> None:
        acct = healthy_account(equity=9_000.0, realized_day_pnl=-700.0)  # both R4 and R3 tripped
        d = evaluate_trade(acct, TradeRequest("BTC/USD", ENTRY, STOP), default_limits())
        assert d.approved is False
        assert d.reason is RejectReason.CIRCUIT_BREAKER

    def test_daily_loss_blocks_entry(self) -> None:
        acct = healthy_account(realized_day_pnl=-600.0)
        d = evaluate_trade(acct, TradeRequest("BTC/USD", ENTRY, STOP), default_limits())
        assert d.approved is False
        assert d.reason is RejectReason.DAILY_LOSS_LIMIT

    def test_max_positions_blocks_entry(self) -> None:
        acct = healthy_account(open_positions=1)
        d = evaluate_trade(acct, TradeRequest("BTC/USD", ENTRY, STOP), default_limits())
        assert d.approved is False
        assert d.reason is RejectReason.MAX_POSITIONS

    def test_open_risk_cap_blocks_when_new_trade_would_exceed_7pct(self) -> None:
        # Existing open risk $780 + capped new ~$90 = $870 > $840 cap.
        limits = RiskLimits(
            max_risk_per_trade_pct=0.02,
            max_total_open_risk_pct=0.07,
            daily_loss_limit_pct=0.05,
            max_drawdown_pct=0.15,
            max_concurrent_positions=5,
            max_notional_pct=0.25,
        )
        acct = healthy_account(open_positions=1, open_risk_dollars=825.0)
        d = evaluate_trade(acct, TradeRequest("BTC/USD", ENTRY, STOP), limits)
        assert d.approved is False
        assert d.reason is RejectReason.MAX_OPEN_RISK

    def test_open_risk_within_cap_is_allowed(self) -> None:
        limits = RiskLimits(max_concurrent_positions=5)
        acct = healthy_account(open_positions=1, open_risk_dollars=500.0)  # 500 + 240 = 740 <= 840
        d = evaluate_trade(acct, TradeRequest("BTC/USD", ENTRY, STOP), limits)
        assert d.approved is True
        assert d.reason is RejectReason.OK

    def test_invalid_stop_is_rejected_not_raised(self) -> None:
        req = TradeRequest("BTC/USD", ENTRY, ENTRY)
        d = evaluate_trade(healthy_account(), req, default_limits())
        assert d.approved is False
        assert d.reason is RejectReason.INVALID_STOP

    def test_approved_size_never_exceeds_per_trade_risk(self) -> None:
        req = TradeRequest("BTC/USD", ENTRY, STOP)
        d = evaluate_trade(healthy_account(), req, default_limits())
        assert d.sizing is not None
        realized_risk = (ENTRY - STOP) * d.sizing.qty
        assert realized_risk <= 240.0 + 1e-6
        assert math.isfinite(d.sizing.qty)
