"""Pure scalar decision logic for the v3 pullback strategy.

No pandas, no I/O, no clock. Every rule is a small function over scalars so the
trading logic is exhaustively unit-testable and identical between live and
backtest. The pandas orchestration lives in ``strategy.py``; it extracts a
``BarSnapshot`` and delegates every *decision* here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .models import BarSnapshot, OrderSide, ScanEvaluation, Signal, StrategyParams


@dataclass(frozen=True)
class ConditionResult:
    passed: bool
    message: str


def check_trend(close: float, ema: float | None, label: str) -> ConditionResult:
    if ema is None:
        return ConditionResult(False, f"{label}: EMA unavailable")
    if close > ema:
        return ConditionResult(True, f"{label} uptrend OK")
    return ConditionResult(False, f"{label} close {close:.2f} <= EMA {ema:.2f}")


def check_vwap(close: float, vwap: float | None, params: StrategyParams) -> ConditionResult:
    if vwap is None or vwap <= 0:
        return ConditionResult(False, "VWAP unavailable")
    dist_pct = abs(close - vwap) / vwap
    if dist_pct <= params.vwap_pullback_pct:
        return ConditionResult(True, f"VWAP OK ({dist_pct * 100:.2f}% away)")
    return ConditionResult(
        False, f"VWAP dist {dist_pct * 100:.2f}% > {params.vwap_pullback_pct * 100:.1f}%"
    )


def check_rsi(
    rsi: float | None, rsi_prev: float | None, params: StrategyParams
) -> ConditionResult:
    if rsi is None:
        return ConditionResult(False, "RSI unavailable")
    if rsi > params.rsi_oversold:
        return ConditionResult(False, f"RSI={rsi:.1f} > {params.rsi_oversold:.0f}")
    if params.require_rsi_turning_up:
        if rsi_prev is None:
            return ConditionResult(False, "RSI prev unavailable")
        if rsi <= rsi_prev:
            return ConditionResult(False, f"RSI not turning up ({rsi_prev:.1f} -> {rsi:.1f})")
    return ConditionResult(True, f"RSI OK ({rsi:.1f})")


def check_macd(
    hist: float | None, hist_prev: float | None, params: StrategyParams
) -> ConditionResult:
    if not params.require_macd_positive and not params.require_macd_expanding:
        return ConditionResult(True, "MACD filter off")
    if hist is None:
        return ConditionResult(False, "MACD unavailable")
    if params.require_macd_positive and hist <= 0:
        return ConditionResult(False, f"MACD hist {hist:.6f} <= 0")
    if params.require_macd_expanding:
        if hist_prev is None or hist <= hist_prev:
            return ConditionResult(False, "MACD not expanding")
    return ConditionResult(True, "MACD OK")


def check_bollinger(
    close: float, bb_lower: float | None, bb_mid: float | None, params: StrategyParams
) -> ConditionResult:
    if not params.bollinger_lower_half_only:
        return ConditionResult(True, "Bollinger filter off")
    if bb_lower is None or bb_mid is None:
        return ConditionResult(False, "Bollinger bands unavailable")
    lower_half_top = (bb_lower + bb_mid) / 2.0
    touch_tol = bb_lower * 0.001
    if close <= bb_lower + touch_tol:
        return ConditionResult(True, "At lower BB")
    if close <= lower_half_top:
        return ConditionResult(True, "In lower BB half")
    return ConditionResult(False, f"Price {close:.2f} above lower BB half ({lower_half_top:.2f})")


def check_volume(snapshot: BarSnapshot, params: StrategyParams) -> ConditionResult:
    # Crypto bars frequently report volume==0; the filter is off by default for
    # crypto and only runs when explicitly required.
    if params.crypto_mode and not params.require_volume_spike:
        return ConditionResult(True, "Volume skipped (crypto mode)")
    if not params.require_volume_spike:
        return ConditionResult(True, "Volume filter off")
    vol = snapshot.volume if snapshot.volume > 0 else snapshot.prev_volume
    if snapshot.vol_sma is None or snapshot.vol_sma <= 0:
        return ConditionResult(False, "Volume SMA unavailable")
    if vol > snapshot.vol_sma * params.volume_spike_mult:
        return ConditionResult(True, "Volume spike OK")
    return ConditionResult(False, "Volume spike failed")


def is_near_signal(num_passes: int, num_failures: int) -> bool:
    """A 'near miss' worth surfacing in logs: mostly passing, few failures."""
    return num_failures <= 2 and num_passes >= 3


def evaluate_conditions(results: list[ConditionResult]) -> ScanEvaluation:
    """Aggregate ordered condition results into a verdict."""
    passes = tuple(r.message for r in results if r.passed)
    failures = tuple(r.message for r in results if not r.passed)
    near = is_near_signal(len(passes), len(failures))
    if failures:
        return ScanEvaluation(
            eligible=False,
            summary="Eligible? No -> " + "; ".join(failures),
            passes=passes,
            failures=failures,
            near_signal=near,
        )
    return ScanEvaluation(
        eligible=True,
        summary="Eligible? Yes -> " + ", ".join(passes[:6]),
        passes=passes,
        failures=(),
        near_signal=True,
    )


def build_signal(
    symbol: str,
    entry_price: float,
    params: StrategyParams,
    reasons: tuple[str, ...],
    now: datetime | None = None,
) -> Signal:
    """Construct a long signal with bracket prices derived from the entry."""
    stop_price = round(entry_price * (1.0 - params.stop_loss_pct), 2)
    take_profit_price = round(entry_price * (1.0 + params.take_profit_pct), 2)
    trimmed = reasons[:6]
    confidence = min(1.0, len(trimmed) / 6.0)
    return Signal(
        symbol=symbol,
        side=OrderSide.BUY,
        entry_price=entry_price,
        stop_price=stop_price,
        take_profit_price=take_profit_price,
        confidence=confidence,
        reasons=trimmed,
        timestamp=now,
    )


def decide_exit(
    last_low: float,
    last_high: float,
    rsi: float | None,
    hold_minutes: float,
    entry_price: float,
    params: StrategyParams,
) -> str | None:
    """Soft-exit decision. Bracket orders still enforce hard SL/TP at the broker;
    this mirrors them so the monitoring loop can act on bar data too.

    Order of precedence: time stop -> RSI overbought -> stop loss -> take profit.
    """
    if hold_minutes >= params.max_hold_minutes:
        return "time_stop"
    if rsi is not None and rsi >= params.rsi_overbought:
        return "rsi_overbought"
    stop_price = entry_price * (1.0 - params.stop_loss_pct)
    take_profit_price = entry_price * (1.0 + params.take_profit_pct)
    if last_low <= stop_price:
        return "stop_loss"
    if last_high >= take_profit_price:
        return "take_profit"
    return None
