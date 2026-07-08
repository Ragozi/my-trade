"""Exhaustive tests for the pure scalar strategy logic (no pandas)."""

from __future__ import annotations

import dataclasses
from datetime import datetime

from my_trade.core.strategy import (
    BarSnapshot,
    ConditionResult,
    OrderSide,
    StrategyParams,
    build_signal,
    check_bollinger,
    check_macd,
    check_rsi,
    check_trend,
    check_volume,
    check_vwap,
    decide_exit,
    evaluate_conditions,
    is_near_signal,
)

P = StrategyParams()


def params(**overrides: object) -> StrategyParams:
    return dataclasses.replace(P, **overrides)


class TestTrend:
    def test_ema_unavailable_fails(self) -> None:
        assert check_trend(100.0, None, "5m").passed is False

    def test_close_above_ema_passes(self) -> None:
        assert check_trend(101.0, 100.0, "5m").passed is True

    def test_close_at_or_below_ema_fails(self) -> None:
        assert check_trend(100.0, 100.0, "5m").passed is False


class TestVwap:
    def test_unavailable_fails(self) -> None:
        assert check_vwap(100.0, None, P).passed is False
        assert check_vwap(100.0, 0.0, P).passed is False

    def test_within_pullback_passes(self) -> None:
        # 0.5% away, default pullback 1.2%
        assert check_vwap(100.5, 100.0, P).passed is True

    def test_outside_pullback_fails(self) -> None:
        # 5% away
        assert check_vwap(105.0, 100.0, P).passed is False

    def test_momentum_above_vwap_passes(self) -> None:
        p = params(momentum_above_vwap=True)
        assert check_vwap(102.0, 100.0, p).passed is True

    def test_momentum_below_vwap_fails(self) -> None:
        p = params(momentum_above_vwap=True)
        assert check_vwap(99.0, 100.0, p).passed is False


class TestRsi:
    def test_unavailable_fails(self) -> None:
        assert check_rsi(None, 40.0, P).passed is False

    def test_above_oversold_fails(self) -> None:
        assert check_rsi(50.0, 49.0, P).passed is False

    def test_turning_up_required_prev_missing_fails(self) -> None:
        assert check_rsi(40.0, None, P).passed is False

    def test_not_turning_up_fails(self) -> None:
        assert check_rsi(38.0, 39.0, P).passed is False

    def test_oversold_and_turning_up_passes(self) -> None:
        assert check_rsi(40.0, 38.0, P).passed is True

    def test_turning_up_disabled_ignores_prev(self) -> None:
        pr = params(require_rsi_turning_up=False)
        assert check_rsi(40.0, 41.0, pr).passed is True


class TestMacd:
    def test_unavailable_fails(self) -> None:
        assert check_macd(None, 0.1, P).passed is False

    def test_non_positive_fails(self) -> None:
        assert check_macd(0.0, -0.1, P).passed is False

    def test_prev_missing_fails(self) -> None:
        assert check_macd(0.2, None, P).passed is False

    def test_not_expanding_fails(self) -> None:
        assert check_macd(0.2, 0.3, P).passed is False

    def test_positive_and_expanding_passes(self) -> None:
        assert check_macd(0.3, 0.2, P).passed is True

    def test_filter_off_passes_negative_hist(self) -> None:
        pr = params(require_macd_positive=False, require_macd_expanding=False)
        assert check_macd(-1.0, -2.0, pr).passed is True


class TestBollinger:
    def test_filter_off_passes(self) -> None:
        pr = params(bollinger_lower_half_only=False)
        assert check_bollinger(999.0, None, None, pr).passed is True

    def test_bands_unavailable_fails(self) -> None:
        assert check_bollinger(100.0, None, 110.0, P).passed is False

    def test_touching_lower_band_passes(self) -> None:
        assert check_bollinger(100.0, 100.0, 120.0, P).passed is True

    def test_in_lower_half_passes(self) -> None:
        # lower=100, mid=120 -> lower-half top = 110
        assert check_bollinger(108.0, 100.0, 120.0, P).passed is True

    def test_above_lower_half_fails(self) -> None:
        assert check_bollinger(115.0, 100.0, 120.0, P).passed is False


class TestVolume:
    def test_crypto_mode_skips(self) -> None:
        pr = params(crypto_mode=True, require_volume_spike=False)
        snap = _snap(volume=0.0)
        assert check_volume(snap, pr).passed is True

    def test_filter_off_non_crypto_passes(self) -> None:
        pr = params(crypto_mode=False, require_volume_spike=False)
        assert check_volume(_snap(), pr).passed is True

    def test_required_sma_unavailable_fails(self) -> None:
        pr = params(crypto_mode=False, require_volume_spike=True)
        snap = _snap(volume=1000.0, vol_sma=None)
        assert check_volume(snap, pr).passed is False

    def test_required_spike_passes_using_prev_when_zero(self) -> None:
        pr = params(crypto_mode=False, require_volume_spike=True, volume_spike_mult=1.2)
        snap = _snap(volume=0.0, prev_volume=1000.0, vol_sma=100.0)
        assert check_volume(snap, pr).passed is True

    def test_required_spike_below_threshold_fails(self) -> None:
        pr = params(crypto_mode=False, require_volume_spike=True, volume_spike_mult=1.2)
        snap = _snap(volume=110.0, vol_sma=100.0)
        assert check_volume(snap, pr).passed is False


class TestNearSignalAndAggregate:
    def test_is_near_signal_boundaries(self) -> None:
        assert is_near_signal(num_passes=3, num_failures=2) is True
        assert is_near_signal(num_passes=2, num_failures=2) is False
        assert is_near_signal(num_passes=5, num_failures=3) is False

    def test_aggregate_all_pass_is_eligible(self) -> None:
        results = [ConditionResult(True, f"ok{i}") for i in range(5)]
        ev = evaluate_conditions(results)
        assert ev.eligible is True
        assert ev.summary.startswith("Eligible? Yes")
        assert ev.failures == ()
        assert len(ev.passes) == 5

    def test_aggregate_with_failures_not_eligible(self) -> None:
        results = [
            ConditionResult(True, "ok1"),
            ConditionResult(False, "bad1"),
            ConditionResult(True, "ok2"),
        ]
        ev = evaluate_conditions(results)
        assert ev.eligible is False
        assert "bad1" in ev.summary
        assert ev.failures == ("bad1",)


class TestBuildSignal:
    def test_bracket_prices_and_side(self) -> None:
        sig = build_signal("BTC/USD", 100_000.0, P, reasons=("a", "b"))
        assert sig.side is OrderSide.BUY
        assert sig.stop_price == round(100_000.0 * (1 - P.stop_loss_pct), 2)
        assert sig.take_profit_price == round(100_000.0 * (1 + P.take_profit_pct), 2)

    def test_confidence_and_reason_trimming(self) -> None:
        reasons = tuple(f"r{i}" for i in range(10))
        sig = build_signal("BTC/USD", 100.0, P, reasons=reasons)
        assert len(sig.reasons) == 6
        assert sig.confidence == 1.0

    def test_timestamp_passthrough(self) -> None:
        now = datetime(2026, 1, 1, 12, 0)
        sig = build_signal("BTC/USD", 100.0, P, reasons=(), now=now)
        assert sig.timestamp == now
        assert sig.confidence == 0.0


class TestDecideExit:
    def test_time_stop_has_precedence(self) -> None:
        # Even with a profitable high, the time stop wins.
        result = decide_exit(
            last_low=100.0, last_high=200.0, rsi=20.0,
            hold_minutes=P.max_hold_minutes, entry_price=100.0, params=P,
        )
        assert result == "time_stop"

    def test_rsi_overbought(self) -> None:
        result = decide_exit(
            last_low=100.0, last_high=100.0, rsi=P.rsi_overbought,
            hold_minutes=1.0, entry_price=100.0, params=P,
        )
        assert result == "rsi_overbought"

    def test_stop_loss(self) -> None:
        entry = 100.0
        stop = entry * (1 - P.stop_loss_pct)
        result = decide_exit(
            last_low=stop - 0.01, last_high=entry, rsi=None,
            hold_minutes=1.0, entry_price=entry, params=P,
        )
        assert result == "stop_loss"

    def test_take_profit(self) -> None:
        entry = 100.0
        tp = entry * (1 + P.take_profit_pct)
        result = decide_exit(
            last_low=entry, last_high=tp + 0.01, rsi=None,
            hold_minutes=1.0, entry_price=entry, params=P,
        )
        assert result == "take_profit"

    def test_no_exit(self) -> None:
        result = decide_exit(
            last_low=100.0, last_high=100.5, rsi=50.0,
            hold_minutes=1.0, entry_price=100.0, params=P,
        )
        assert result is None


def _snap(
    *,
    close: float = 100.0,
    vwap: float | None = 100.0,
    rsi: float | None = 40.0,
    rsi_prev: float | None = 38.0,
    macd_hist: float | None = 0.2,
    macd_hist_prev: float | None = 0.1,
    bb_lower: float | None = 99.0,
    bb_mid: float | None = 110.0,
    volume: float = 1000.0,
    prev_volume: float = 1000.0,
    vol_sma: float | None = 500.0,
) -> BarSnapshot:
    return BarSnapshot(
        close=close, vwap=vwap, rsi=rsi, rsi_prev=rsi_prev,
        macd_hist=macd_hist, macd_hist_prev=macd_hist_prev,
        bb_lower=bb_lower, bb_mid=bb_mid, volume=volume,
        prev_volume=prev_volume, vol_sma=vol_sma,
    )
