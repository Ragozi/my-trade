"""Typed contracts for the strategy layer (no behavior, no I/O)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from my_trade.core.models import OrderSide

if TYPE_CHECKING:
    from my_trade.config import Settings

__all__ = [
    "BarSnapshot",
    "OrderSide",
    "ScanEvaluation",
    "Signal",
    "StrategyParams",
]


@dataclass(frozen=True)
class Signal:
    """A proposed long entry produced by the strategy.

    The strategy proposes prices; the risk engine sizes and approves. The
    strategy never decides quantity or notional.
    """

    symbol: str
    side: OrderSide
    entry_price: float
    stop_price: float
    take_profit_price: float
    confidence: float
    reasons: tuple[str, ...] = ()
    timestamp: datetime | None = None


@dataclass(frozen=True)
class ScanEvaluation:
    """Structured, log-free result of one entry evaluation."""

    eligible: bool
    summary: str
    passes: tuple[str, ...] = ()
    failures: tuple[str, ...] = ()
    near_signal: bool = False


@dataclass(frozen=True)
class BarSnapshot:
    """Scalar view of the latest (and previous) bar's indicators.

    This is the bridge between pandas-heavy indicator code and the pure scalar
    decision logic. ``None`` means the indicator was unavailable (warm-up / NaN).
    """

    close: float
    vwap: float | None
    rsi: float | None
    rsi_prev: float | None
    macd_hist: float | None
    macd_hist_prev: float | None
    bb_lower: float | None
    bb_mid: float | None
    volume: float
    prev_volume: float
    vol_sma: float | None


@dataclass(frozen=True)
class StrategyParams:
    """All numeric/boolean knobs the strategy needs (v3 BTC defaults)."""

    rsi_period: int = 14
    rsi_oversold: float = 42.0
    rsi_overbought: float = 68.0
    ema_trend: int = 20
    vwap_pullback_pct: float = 0.012
    volume_spike_mult: float = 1.2
    volume_sma_period: int = 20
    stop_loss_pct: float = 0.0065
    take_profit_pct: float = 0.017
    max_hold_minutes: int = 15
    require_5m_uptrend: bool = False
    require_15m_uptrend: bool = True
    require_volume_spike: bool = False
    require_rsi_turning_up: bool = True
    bollinger_lower_half_only: bool = True
    bollinger_period: int = 20
    bollinger_std: float = 2.0
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    crypto_mode: bool = True

    @classmethod
    def from_settings(cls, settings: Settings) -> StrategyParams:
        """Build params from the application settings (config layer)."""
        s = settings.strategy
        return cls(
            rsi_period=s.rsi_period,
            rsi_oversold=s.rsi_oversold,
            rsi_overbought=s.rsi_overbought,
            ema_trend=s.ema_trend,
            vwap_pullback_pct=s.vwap_pullback_pct,
            volume_spike_mult=s.volume_spike_mult,
            volume_sma_period=s.volume_sma_period,
            stop_loss_pct=s.stop_loss_pct,
            take_profit_pct=s.take_profit_pct,
            max_hold_minutes=s.max_hold_minutes,
            require_5m_uptrend=s.require_5m_uptrend,
            require_15m_uptrend=s.require_15m_uptrend,
            require_volume_spike=s.require_volume_spike,
            require_rsi_turning_up=s.require_rsi_turning_up,
            bollinger_lower_half_only=s.bollinger_lower_half_only,
            bollinger_period=s.bollinger_period,
            bollinger_std=s.bollinger_std,
            macd_fast=s.macd_fast,
            macd_slow=s.macd_slow,
            macd_signal=s.macd_signal,
            crypto_mode=settings.crypto_mode,
        )
