"""Application configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from typing import List

from dotenv import load_dotenv

load_dotenv()

DEFAULT_CRYPTO_SYMBOL = "BTC/USD"


def _env_bool(key: str, default: bool) -> bool:
    value = os.getenv(key)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(key: str, default: float) -> float:
    value = os.getenv(key)
    return float(value) if value is not None else default


def _env_int(key: str, default: int) -> int:
    value = os.getenv(key)
    return int(value) if value is not None else default


def _parse_symbols(raw: str) -> List[str]:
    seen: set[str] = set()
    out: List[str] = []
    for s in raw.split(","):
        sym = s.strip().upper()
        if sym and sym not in seen:
            seen.add(sym)
            out.append(sym)
    return out


@dataclass(frozen=True)
class Settings:
    """BTC/USD crypto scalper v3 — pullback-friendly, configurable filters."""

    api_key: str
    api_secret: str
    paper_trading: bool = True
    allow_live_trading: bool = False

    crypto_mode: bool = True
    symbols: List[str] = field(default_factory=lambda: [DEFAULT_CRYPTO_SYMBOL])

    dashboard_host: str = "127.0.0.1"
    dashboard_port: int = 8765
    journal_db: str = "logs/journal.db"

    notional_per_trade: float = 12.0

    entry_timeframe: str = "1Min"
    trend_timeframe: str = "5Min"
    trend_timeframe_15m: str = "15Min"
    bar_limit: int = 200

    # v3 strategy — BTC-optimized defaults
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

    verbose_debug: bool = False
    log_every_n_scans: int = 5

    max_daily_loss_pct: float = 0.02
    max_open_positions: int = 1
    max_entries_per_symbol_per_day: int = 50
    scan_interval_seconds: int = 60

    backtest_symbols: List[str] = field(default_factory=lambda: [DEFAULT_CRYPTO_SYMBOL])

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    slack_bot_token: str = ""
    slack_channel: str = "my-trade"
    slack_webhook_url: str = ""
    slack_notify_scans: bool = False

    log_dir: str = "logs"
    daily_state_file: str = "logs/daily_state.json"

    def validate_for_trading(self) -> None:
        if not self.api_key or not self.api_secret:
            raise ValueError(
                "APCA_API_KEY_ID and APCA_API_SECRET_KEY must be set in .env"
            )
        if not self.paper_trading and not self.allow_live_trading:
            raise ValueError(
                "Live trading requires PAPER_TRADING=false and ALLOW_LIVE_TRADING=true"
            )
        if self.crypto_mode and not self.symbols:
            raise ValueError("At least one crypto symbol is required")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    symbols_raw = os.getenv("CRYPTO_SYMBOLS", DEFAULT_CRYPTO_SYMBOL)
    symbols = _parse_symbols(symbols_raw)
    if not symbols:
        symbols = [DEFAULT_CRYPTO_SYMBOL]

    crypto_mode = _env_bool("CRYPTO_MODE", True)
    # Crypto: volume spike off by default (Alpaca often returns vol=0)
    vol_default = False if crypto_mode else _env_bool("REQUIRE_VOLUME_SPIKE", False)
    require_volume = _env_bool("REQUIRE_VOLUME_SPIKE", vol_default)
    if crypto_mode and os.getenv("REQUIRE_VOLUME_SPIKE") is None:
        require_volume = False

    return Settings(
        api_key=os.getenv("APCA_API_KEY_ID", ""),
        api_secret=os.getenv("APCA_API_SECRET_KEY", ""),
        paper_trading=_env_bool("PAPER_TRADING", True),
        allow_live_trading=_env_bool("ALLOW_LIVE_TRADING", False),
        crypto_mode=crypto_mode,
        symbols=symbols,
        dashboard_host=os.getenv("DASHBOARD_HOST", "127.0.0.1"),
        dashboard_port=_env_int("DASHBOARD_PORT", 8765),
        journal_db=os.getenv("JOURNAL_DB", "logs/journal.db"),
        notional_per_trade=_env_float("NOTIONAL_PER_TRADE", 12.0),
        entry_timeframe=os.getenv("ENTRY_TIMEFRAME", "1Min"),
        trend_timeframe=os.getenv("TREND_TIMEFRAME", "5Min"),
        trend_timeframe_15m=os.getenv("TREND_TIMEFRAME_15M", "15Min"),
        bar_limit=_env_int("BAR_LIMIT", 200),
        rsi_period=_env_int("RSI_PERIOD", 14),
        rsi_oversold=_env_float("RSI_OVERSOLD", 42.0),
        rsi_overbought=_env_float("RSI_OVERBOUGHT", 68.0),
        ema_trend=_env_int("EMA_TREND", 20),
        vwap_pullback_pct=_env_float("VWAP_PULLBACK_PCT", 0.012),
        volume_spike_mult=_env_float("VOLUME_SPIKE_MULT", 1.2),
        volume_sma_period=_env_int("VOLUME_SMA_PERIOD", 20),
        stop_loss_pct=_env_float("STOP_LOSS_PCT", 0.0065),
        take_profit_pct=_env_float("TAKE_PROFIT_PCT", 0.017),
        max_hold_minutes=_env_int("MAX_HOLD_MINUTES", 15),
        require_5m_uptrend=_env_bool("REQUIRE_5M_UPTREND", False),
        require_15m_uptrend=_env_bool("REQUIRE_15M_UPTREND", True),
        require_volume_spike=require_volume,
        require_above_ema9=_env_bool("REQUIRE_ABOVE_EMA9", False),
        require_rsi_turning_up=_env_bool("REQUIRE_RSI_TURNING_UP", True),
        bollinger_lower_half_only=_env_bool("BOLLINGER_LOWER_HALF_ONLY", True),
        bollinger_period=_env_int("BOLLINGER_PERIOD", 20),
        bollinger_std=_env_float("BOLLINGER_STD", 2.0),
        macd_fast=_env_int("MACD_FAST", 12),
        macd_slow=_env_int("MACD_SLOW", 26),
        macd_signal=_env_int("MACD_SIGNAL", 9),
        verbose_debug=_env_bool("VERBOSE_DEBUG", False),
        log_every_n_scans=_env_int("LOG_EVERY_N_SCANS", 5),
        max_daily_loss_pct=_env_float("MAX_DAILY_LOSS_PCT", 0.02),
        max_open_positions=_env_int("MAX_OPEN_POSITIONS", 1),
        max_entries_per_symbol_per_day=_env_int(
            "MAX_ENTRIES_PER_SYMBOL_PER_DAY", 50
        ),
        scan_interval_seconds=_env_int("SCAN_INTERVAL_SECONDS", 60),
        backtest_symbols=symbols,
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
        slack_bot_token=os.getenv("SLACK_BOT_TOKEN", ""),
        slack_channel=os.getenv("SLACK_CHANNEL", "my-trade"),
        slack_webhook_url=os.getenv("SLACK_WEBHOOK_URL", ""),
        slack_notify_scans=_env_bool("SLACK_NOTIFY_SCANS", False),
        log_dir=os.getenv("LOG_DIR", "logs"),
        daily_state_file=os.getenv("DAILY_STATE_FILE", "logs/daily_state.json"),
    )
