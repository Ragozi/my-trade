"""Typed, validated application settings.

Settings are split into cohesive frozen groups and composed into one ``Settings``
object. The loader is pure: it reads from an explicit ``env`` mapping (defaulting
to ``os.environ`` + ``.env``) so it can be tested without mutating global state.

Risk parameters are the single source of truth for the deterministic risk engine
via :meth:`RiskSettings.to_limits` (SCOPE.md §5b: R1 2%, R2 7%, R3 5%, R4 15%).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from my_trade.core.risk import RiskLimits
from my_trade.core.screening import (
    DEFAULT_CRYPTO_UNIVERSE,
    ScreenerCriteria,
)

from .parsing import env_bool, env_float, env_int, env_str, parse_symbols

DEFAULT_CRYPTO_SYMBOL = "BTC/USD"


@dataclass(frozen=True)
class AlpacaSettings:
    """Broker credentials + execution mode. Secrets only ever come from env."""

    api_key: str
    api_secret: str
    paper_trading: bool = True
    allow_live_trading: bool = False


@dataclass(frozen=True)
class RiskSettings:
    """Deterministic risk limits (fractions of equity). See SCOPE.md §5b."""

    max_risk_per_trade_pct: float = 0.02      # R1
    max_total_open_risk_pct: float = 0.07     # R2
    daily_loss_limit_pct: float = 0.05        # R3
    max_drawdown_pct: float = 0.15            # R4
    max_concurrent_positions: int = 1
    max_entries_per_symbol_per_day: int = 10

    def to_limits(self) -> RiskLimits:
        """Project into the engine's ``RiskLimits`` contract."""
        return RiskLimits(
            max_risk_per_trade_pct=self.max_risk_per_trade_pct,
            max_total_open_risk_pct=self.max_total_open_risk_pct,
            daily_loss_limit_pct=self.daily_loss_limit_pct,
            max_drawdown_pct=self.max_drawdown_pct,
            max_concurrent_positions=self.max_concurrent_positions,
        )

    def validate(self) -> None:
        pcts = {
            "max_risk_per_trade_pct": self.max_risk_per_trade_pct,
            "max_total_open_risk_pct": self.max_total_open_risk_pct,
            "daily_loss_limit_pct": self.daily_loss_limit_pct,
            "max_drawdown_pct": self.max_drawdown_pct,
        }
        for name, value in pcts.items():
            if not 0.0 < value <= 1.0:
                raise ValueError(f"{name} must be in (0, 1], got {value}")
        if self.max_risk_per_trade_pct > self.max_total_open_risk_pct:
            raise ValueError("max_risk_per_trade_pct cannot exceed max_total_open_risk_pct")
        if self.max_concurrent_positions < 1:
            raise ValueError("max_concurrent_positions must be >= 1")
        if self.max_entries_per_symbol_per_day < 1:
            raise ValueError("max_entries_per_symbol_per_day must be >= 1")


@dataclass(frozen=True)
class StrategySettings:
    """v3 BTC pullback parameters (pure numbers; no behavior here)."""

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
    require_above_ema9: bool = False
    require_rsi_turning_up: bool = True
    bollinger_lower_half_only: bool = True
    bollinger_period: int = 20
    bollinger_std: float = 2.0
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9


@dataclass(frozen=True)
class ScreenerSettings:
    """Deterministic universe-selection knobs (SCOPE.md screener policy).

    Disabled by default: when ``enabled`` is False the orchestrator trades the
    statically configured ``symbols`` exactly as before. When enabled, the
    screener narrows ``universe`` down to the best ``top_n`` names each refresh.
    """

    enabled: bool = False
    universe: tuple[str, ...] = DEFAULT_CRYPTO_UNIVERSE
    timeframe: str = "15Min"
    bar_limit: int = 50
    atr_period: int = 14
    lookback: int = 20
    refresh_seconds: int = 900
    min_price: float = 0.0
    max_price: float = float("inf")
    min_dollar_volume: float = 0.0
    min_atr_pct: float = 0.0
    max_atr_pct: float = 1.0
    min_bars: int = 20
    top_n: int = 5
    weight_volatility: float = 1.0
    weight_liquidity: float = 1.0

    def to_criteria(self) -> ScreenerCriteria:
        """Project into the screener's ``ScreenerCriteria`` contract."""
        return ScreenerCriteria(
            min_price=self.min_price,
            max_price=self.max_price,
            min_dollar_volume=self.min_dollar_volume,
            min_atr_pct=self.min_atr_pct,
            max_atr_pct=self.max_atr_pct,
            min_bars=self.min_bars,
            top_n=self.top_n,
            weight_volatility=self.weight_volatility,
            weight_liquidity=self.weight_liquidity,
        )


@dataclass(frozen=True)
class RuntimeSettings:
    """Operational knobs: timeframes, cadence, logging, file paths."""

    entry_timeframe: str = "1Min"
    trend_timeframe: str = "5Min"
    trend_timeframe_15m: str = "15Min"
    bar_limit: int = 200
    scan_interval_seconds: int = 60
    verbose_debug: bool = False
    log_every_n_scans: int = 5
    log_dir: str = "logs"
    daily_state_file: str = "logs/daily_state.json"
    journal_db: str = "logs/journal.db"


@dataclass(frozen=True)
class Settings:
    """Top-level composed settings object."""

    alpaca: AlpacaSettings
    risk: RiskSettings
    strategy: StrategySettings
    runtime: RuntimeSettings
    screener: ScreenerSettings = ScreenerSettings()
    crypto_mode: bool = True
    symbols: tuple[str, ...] = (DEFAULT_CRYPTO_SYMBOL,)

    def validate(self) -> None:
        """Always-on structural validation (safe even outside trading)."""
        self.risk.validate()
        if not self.symbols:
            raise ValueError("at least one symbol is required")

    def validate_for_trading(self) -> None:
        """Stricter checks required before any order can be placed."""
        self.validate()
        if not self.alpaca.api_key or not self.alpaca.api_secret:
            raise ValueError("APCA_API_KEY_ID and APCA_API_SECRET_KEY must be set")
        if not self.alpaca.paper_trading and not self.alpaca.allow_live_trading:
            raise ValueError(
                "Live trading requires PAPER_TRADING=false AND ALLOW_LIVE_TRADING=true"
            )


def _load_alpaca(env: Mapping[str, str]) -> AlpacaSettings:
    return AlpacaSettings(
        api_key=env_str(env, "APCA_API_KEY_ID", ""),
        api_secret=env_str(env, "APCA_API_SECRET_KEY", ""),
        paper_trading=env_bool(env, "PAPER_TRADING", True),
        allow_live_trading=env_bool(env, "ALLOW_LIVE_TRADING", False),
    )


def _load_risk(env: Mapping[str, str]) -> RiskSettings:
    return RiskSettings(
        max_risk_per_trade_pct=env_float(env, "MAX_RISK_PER_TRADE_PCT", 0.02),
        max_total_open_risk_pct=env_float(env, "MAX_TOTAL_OPEN_RISK_PCT", 0.07),
        daily_loss_limit_pct=env_float(env, "DAILY_LOSS_LIMIT_PCT", 0.05),
        max_drawdown_pct=env_float(env, "MAX_DRAWDOWN_PCT", 0.15),
        max_concurrent_positions=env_int(env, "MAX_OPEN_POSITIONS", 1),
        max_entries_per_symbol_per_day=env_int(env, "MAX_ENTRIES_PER_SYMBOL_PER_DAY", 10),
    )


def _load_strategy(env: Mapping[str, str]) -> StrategySettings:
    return StrategySettings(
        rsi_period=env_int(env, "RSI_PERIOD", 14),
        rsi_oversold=env_float(env, "RSI_OVERSOLD", 42.0),
        rsi_overbought=env_float(env, "RSI_OVERBOUGHT", 68.0),
        ema_trend=env_int(env, "EMA_TREND", 20),
        vwap_pullback_pct=env_float(env, "VWAP_PULLBACK_PCT", 0.012),
        volume_spike_mult=env_float(env, "VOLUME_SPIKE_MULT", 1.2),
        volume_sma_period=env_int(env, "VOLUME_SMA_PERIOD", 20),
        stop_loss_pct=env_float(env, "STOP_LOSS_PCT", 0.0065),
        take_profit_pct=env_float(env, "TAKE_PROFIT_PCT", 0.017),
        max_hold_minutes=env_int(env, "MAX_HOLD_MINUTES", 15),
        require_5m_uptrend=env_bool(env, "REQUIRE_5M_UPTREND", False),
        require_15m_uptrend=env_bool(env, "REQUIRE_15M_UPTREND", True),
        require_volume_spike=env_bool(env, "REQUIRE_VOLUME_SPIKE", False),
        require_above_ema9=env_bool(env, "REQUIRE_ABOVE_EMA9", False),
        require_rsi_turning_up=env_bool(env, "REQUIRE_RSI_TURNING_UP", True),
        bollinger_lower_half_only=env_bool(env, "BOLLINGER_LOWER_HALF_ONLY", True),
        bollinger_period=env_int(env, "BOLLINGER_PERIOD", 20),
        bollinger_std=env_float(env, "BOLLINGER_STD", 2.0),
        macd_fast=env_int(env, "MACD_FAST", 12),
        macd_slow=env_int(env, "MACD_SLOW", 26),
        macd_signal=env_int(env, "MACD_SIGNAL", 9),
    )


def _load_screener(env: Mapping[str, str]) -> ScreenerSettings:
    raw_universe = env_str(env, "SCREENER_UNIVERSE", "")
    universe = tuple(parse_symbols(raw_universe)) if raw_universe else DEFAULT_CRYPTO_UNIVERSE
    return ScreenerSettings(
        enabled=env_bool(env, "USE_SCREENER", False),
        universe=universe,
        timeframe=env_str(env, "SCREENER_TIMEFRAME", "15Min"),
        bar_limit=env_int(env, "SCREENER_BAR_LIMIT", 50),
        atr_period=env_int(env, "SCREENER_ATR_PERIOD", 14),
        lookback=env_int(env, "SCREENER_LOOKBACK", 20),
        refresh_seconds=env_int(env, "SCREENER_REFRESH_SECONDS", 900),
        min_price=env_float(env, "SCREENER_MIN_PRICE", 0.0),
        max_price=env_float(env, "SCREENER_MAX_PRICE", float("inf")),
        min_dollar_volume=env_float(env, "SCREENER_MIN_DOLLAR_VOLUME", 0.0),
        min_atr_pct=env_float(env, "SCREENER_MIN_ATR_PCT", 0.0),
        max_atr_pct=env_float(env, "SCREENER_MAX_ATR_PCT", 1.0),
        min_bars=env_int(env, "SCREENER_MIN_BARS", 20),
        top_n=env_int(env, "SCREENER_TOP_N", 5),
        weight_volatility=env_float(env, "SCREENER_WEIGHT_VOLATILITY", 1.0),
        weight_liquidity=env_float(env, "SCREENER_WEIGHT_LIQUIDITY", 1.0),
    )


def _load_runtime(env: Mapping[str, str]) -> RuntimeSettings:
    return RuntimeSettings(
        entry_timeframe=env_str(env, "ENTRY_TIMEFRAME", "1Min"),
        trend_timeframe=env_str(env, "TREND_TIMEFRAME", "5Min"),
        trend_timeframe_15m=env_str(env, "TREND_TIMEFRAME_15M", "15Min"),
        bar_limit=env_int(env, "BAR_LIMIT", 200),
        scan_interval_seconds=env_int(env, "SCAN_INTERVAL_SECONDS", 60),
        verbose_debug=env_bool(env, "VERBOSE_DEBUG", False),
        log_every_n_scans=env_int(env, "LOG_EVERY_N_SCANS", 5),
        log_dir=env_str(env, "LOG_DIR", "logs"),
        daily_state_file=env_str(env, "DAILY_STATE_FILE", "logs/daily_state.json"),
        journal_db=env_str(env, "JOURNAL_DB", "logs/journal.db"),
    )


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Build a validated ``Settings`` from an env mapping.

    When ``env`` is ``None`` we load ``.env`` (best-effort) and read
    ``os.environ``. Pass an explicit mapping in tests for full determinism.
    """
    if env is None:
        try:
            from dotenv import load_dotenv

            load_dotenv()
        except ImportError:
            pass
        env = os.environ

    symbols = tuple(parse_symbols(env_str(env, "CRYPTO_SYMBOLS", DEFAULT_CRYPTO_SYMBOL)))
    if not symbols:
        symbols = (DEFAULT_CRYPTO_SYMBOL,)

    settings = Settings(
        alpaca=_load_alpaca(env),
        risk=_load_risk(env),
        strategy=_load_strategy(env),
        runtime=_load_runtime(env),
        screener=_load_screener(env),
        crypto_mode=env_bool(env, "CRYPTO_MODE", True),
        symbols=symbols,
    )
    settings.validate()
    return settings
