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
from dataclasses import dataclass, field

from my_trade.core.risk import RiskLimits
from my_trade.core.screening import (
    DEFAULT_CRYPTO_UNIVERSE,
    ScreenerCriteria,
)

from .parsing import env_bool, env_float, env_int, env_str, parse_symbols

DEFAULT_CRYPTO_SYMBOL = "BTC/USD"
DEFAULT_EQUITY_SYMBOLS = "AAPL,MSFT,TSLA,NVDA,AMD"
# Thematic seed: semiconductors + AI/robotics — merged with Alpaca movers, not a trade cap.
DEFAULT_SCREENER_SEED_SYMBOLS = (
    "NVDA,AMD,AVGO,QCOM,MU,AMAT,LRCX,KLAC,MRVL,ARM,INTC,ON,"
    "TSLA,PLTR,ISRG,SYM,TER,PATH,SERV,AI,RKLB,SOFI"
)
ASSET_CLASS_CRYPTO = "crypto"
ASSET_CLASS_EQUITIES = "equities"
VALID_ASSET_CLASSES = (ASSET_CLASS_CRYPTO, ASSET_CLASS_EQUITIES)


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
    daily_profit_target_pct: float = 0.0       # optional R+ : halt entries when day goal hit (0=off)
    max_drawdown_pct: float = 0.15            # R4
    max_concurrent_positions: int = 1
    max_entries_per_symbol_per_day: int = 10
    max_daily_entries: int = 2
    # When set, size and halt on this virtual balance (paper equity may be much larger).
    trading_capital: float = 0.0
    max_notional_pct: float = 0.25  # max single-position notional vs risk equity

    def to_limits(self) -> RiskLimits:
        """Project into the engine's ``RiskLimits`` contract."""
        return RiskLimits(
            max_risk_per_trade_pct=self.max_risk_per_trade_pct,
            max_total_open_risk_pct=self.max_total_open_risk_pct,
            daily_loss_limit_pct=self.daily_loss_limit_pct,
            daily_profit_target_pct=self.daily_profit_target_pct,
            max_drawdown_pct=self.max_drawdown_pct,
            max_concurrent_positions=self.max_concurrent_positions,
            max_notional_pct=self.max_notional_pct,
        )

    def validate(self) -> None:
        pcts = {
            "max_risk_per_trade_pct": self.max_risk_per_trade_pct,
            "max_total_open_risk_pct": self.max_total_open_risk_pct,
            "daily_loss_limit_pct": self.daily_loss_limit_pct,
            "daily_profit_target_pct": self.daily_profit_target_pct,
            "max_drawdown_pct": self.max_drawdown_pct,
        }
        for name, value in pcts.items():
            if not 0.0 < value <= 1.0:
                raise ValueError(f"{name} must be in (0, 1], got {value}")
        if not 0.0 <= self.daily_profit_target_pct <= 1.0:
            raise ValueError(
                f"daily_profit_target_pct must be in [0, 1], got {self.daily_profit_target_pct}"
            )
        if self.max_risk_per_trade_pct > self.max_total_open_risk_pct:
            raise ValueError("max_risk_per_trade_pct cannot exceed max_total_open_risk_pct")
        if self.max_concurrent_positions < 1:
            raise ValueError("max_concurrent_positions must be >= 1")
        if self.max_entries_per_symbol_per_day < 1:
            raise ValueError("max_entries_per_symbol_per_day must be >= 1")
        if self.max_daily_entries < 1:
            raise ValueError("max_daily_entries must be >= 1")
        if self.trading_capital < 0:
            raise ValueError("trading_capital must be >= 0 (0 = use full broker equity)")
        if 0 < self.trading_capital < 500:
            raise ValueError("trading_capital must be at least $500 when enabled")
        if not 0.0 < self.max_notional_pct <= 1.0:
            raise ValueError("max_notional_pct must be in (0, 1]")
        if self.max_notional_pct > 0.50:
            raise ValueError("max_notional_pct above 50% is not allowed for small accounts")


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
    take_profit_pct: float = 0.013
    max_hold_minutes: int = 90
    require_5m_uptrend: bool = False
    require_15m_uptrend: bool = True
    require_volume_spike: bool = False
    require_above_ema9: bool = False
    require_rsi_turning_up: bool = True
    require_macd_positive: bool = True
    require_macd_expanding: bool = True
    bollinger_lower_half_only: bool = True
    momentum_above_vwap: bool = False
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
    min_change_pct: float = 0.0
    min_bars: int = 20
    top_n: int = 5
    weight_volatility: float = 1.0
    weight_liquidity: float = 1.0
    weight_momentum: float = 0.0
    # Dynamic equities universe (Alpaca screener); ignored for crypto.
    seed_symbols: tuple[str, ...] = ()
    exclude_symbols: tuple[str, ...] = ()
    exclude_leveraged_etfs: bool = True
    exclude_large_caps: bool = False
    movers_only: bool = False
    fallback_to_static_symbols: bool = True
    merge_seed_with_movers: bool = True
    use_movers: bool = False
    movers_source: str = "actives"  # actives | gainers | losers | both
    movers_top: int = 20
    movers_min_volume: float = 0.0
    am_refresh_seconds: int = 0

    def to_criteria(self) -> ScreenerCriteria:
        """Project into the screener's ``ScreenerCriteria`` contract."""
        return ScreenerCriteria(
            min_price=self.min_price,
            max_price=self.max_price,
            min_dollar_volume=self.min_dollar_volume,
            min_atr_pct=self.min_atr_pct,
            max_atr_pct=self.max_atr_pct,
            min_change_pct=self.min_change_pct,
            min_bars=self.min_bars,
            top_n=self.top_n,
            weight_volatility=self.weight_volatility,
            weight_liquidity=self.weight_liquidity,
            weight_momentum=self.weight_momentum,
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
class WorkhorseSettings:
    """Cheaper/frequent research tier (OpenAI or xAI Grok)."""

    provider: str = "none"  # none | openai | xai
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    xai_api_key: str = ""
    xai_model: str = "grok-4.3"
    min_interval_seconds: int = 900
    max_calls_per_day: int = 16
    max_tokens: int = 2048
    timeout_seconds: float = 60.0

    @property
    def is_active(self) -> bool:
        return self.provider not in ("", "none")


@dataclass(frozen=True)
class PremiumSettings:
    """Sparse deep-analysis tier (xAI Grok or GPT-4o) when Claude is off."""

    provider: str = "none"  # none | openai | xai
    openai_model: str = "gpt-4o"
    xai_model: str = "grok-4.3"
    min_interval_seconds: int = 1800
    max_calls_per_day: int = 4
    max_tokens: int = 2048
    timeout_seconds: float = 90.0

    @property
    def is_active(self) -> bool:
        return self.provider not in ("", "none")


@dataclass(frozen=True)
class ResearchSettings:
    """Multi-provider research layer knobs (advisory only)."""

    enabled: bool = False
    claude_enabled: bool = False
    tier_mode: str = "both"  # workhorse_only | claude_only | both
    api_key: str = ""
    model: str = "claude-sonnet-4-20250514"
    workhorse: WorkhorseSettings = field(default_factory=WorkhorseSettings)
    premium: PremiumSettings = field(default_factory=PremiumSettings)
    brief_file: str = "logs/research_brief.json"
    max_tokens: int = 4096
    timeout_seconds: float = 60.0
    max_ideas_per_cycle: int = 5
    min_confidence: float = 0.55
    entry_veto_min_confidence: float = 0.10
    min_interval_seconds: int = 300
    max_calls_per_day: int = 100
    require_approval_for_entry: bool = False
    block_avoid_for_entry: bool = True
    block_hold_for_entry: bool = True
    equities_only: bool = True
    memory_file: str = "logs/research_memory.json"
    memory_max_reflections: int = 100
    knowledge_file: str = "logs/trade_knowledge.json"
    knowledge_max_records: int = 10_000
    performance_window: int = 20
    evaluation_file: str = "logs/research_evaluation.json"
    evaluation_max_records: int = 500
    postmortem_enabled: bool = False
    postmortem_max_per_day: int = 1
    market_hours_only: bool = True
    billing_cooldown_seconds: int = 3600

    @property
    def premium_active(self) -> bool:
        """Alternate premium tier (Grok/GPT-4o) when Claude billing is off."""
        return self.premium.is_active and not self.claude_enabled

    @property
    def any_tier_enabled(self) -> bool:
        return self.claude_enabled or self.workhorse.is_active or self.premium_active


@dataclass(frozen=True)
class Settings:
    """Top-level composed settings object."""

    alpaca: AlpacaSettings
    risk: RiskSettings
    strategy: StrategySettings
    runtime: RuntimeSettings
    screener: ScreenerSettings = ScreenerSettings()
    research: ResearchSettings = ResearchSettings()
    asset_class: str = ASSET_CLASS_CRYPTO
    crypto_mode: bool = True
    symbols: tuple[str, ...] = (DEFAULT_CRYPTO_SYMBOL,)

    @property
    def is_equities(self) -> bool:
        return self.asset_class == ASSET_CLASS_EQUITIES

    def validate(self) -> None:
        """Always-on structural validation (safe even outside trading)."""
        self.risk.validate()
        if self.asset_class not in VALID_ASSET_CLASSES:
            raise ValueError(
                f"ASSET_CLASS must be one of {VALID_ASSET_CLASSES}, got {self.asset_class!r}"
            )
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
        rc = self.research
        if rc.claude_enabled and not rc.api_key:
            raise ValueError(
                "ENABLE_CLAUDE=true requires ANTHROPIC_API_KEY in .env"
            )
        wh = rc.workhorse
        if wh.provider == "openai" and not wh.openai_api_key:
            raise ValueError(
                "RESEARCH_WORKHORSE_PROVIDER=openai requires OPENAI_API_KEY in .env"
            )
        if wh.provider == "xai" and not wh.xai_api_key:
            raise ValueError(
                "RESEARCH_WORKHORSE_PROVIDER=xai requires XAI_API_KEY in .env"
            )
        prem = rc.premium
        if rc.premium_active:
            if prem.provider == "openai" and not wh.openai_api_key:
                raise ValueError(
                    "RESEARCH_PREMIUM_PROVIDER=openai requires OPENAI_API_KEY in .env"
                )
            if prem.provider == "xai" and not wh.xai_api_key:
                raise ValueError(
                    "RESEARCH_PREMIUM_PROVIDER=xai requires XAI_API_KEY in .env"
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
        max_total_open_risk_pct=env_float(env, "MAX_TOTAL_OPEN_RISK_PCT", 0.05),
        daily_loss_limit_pct=env_float(env, "DAILY_LOSS_LIMIT_PCT", 0.01),
        daily_profit_target_pct=env_float(env, "DAILY_PROFIT_TARGET_PCT", 0.01),
        max_drawdown_pct=env_float(env, "MAX_DRAWDOWN_PCT", 0.15),
        max_concurrent_positions=env_int(env, "MAX_OPEN_POSITIONS", 1),
        max_entries_per_symbol_per_day=env_int(env, "MAX_ENTRIES_PER_SYMBOL_PER_DAY", 1),
        max_daily_entries=env_int(env, "MAX_DAILY_ENTRIES", 1),
        trading_capital=env_float(env, "TRADING_CAPITAL", 0.0),
        max_notional_pct=env_float(env, "MAX_NOTIONAL_PCT", 0.40),
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
        take_profit_pct=env_float(env, "TAKE_PROFIT_PCT", 0.013),
        max_hold_minutes=env_int(env, "MAX_HOLD_MINUTES", 90),
        require_5m_uptrend=env_bool(env, "REQUIRE_5M_UPTREND", False),
        require_15m_uptrend=env_bool(env, "REQUIRE_15M_UPTREND", True),
        require_volume_spike=env_bool(env, "REQUIRE_VOLUME_SPIKE", False),
        require_above_ema9=env_bool(env, "REQUIRE_ABOVE_EMA9", False),
        require_rsi_turning_up=env_bool(env, "REQUIRE_RSI_TURNING_UP", True),
        require_macd_positive=env_bool(env, "REQUIRE_MACD_POSITIVE", True),
        require_macd_expanding=env_bool(env, "REQUIRE_MACD_EXPANDING", True),
        bollinger_lower_half_only=env_bool(env, "BOLLINGER_LOWER_HALF_ONLY", True),
        momentum_above_vwap=env_bool(env, "MOMENTUM_ABOVE_VWAP", False),
        bollinger_period=env_int(env, "BOLLINGER_PERIOD", 20),
        bollinger_std=env_float(env, "BOLLINGER_STD", 2.0),
        macd_fast=env_int(env, "MACD_FAST", 12),
        macd_slow=env_int(env, "MACD_SLOW", 26),
        macd_signal=env_int(env, "MACD_SIGNAL", 9),
    )


def _load_screener(env: Mapping[str, str]) -> ScreenerSettings:
    raw_universe = env_str(env, "SCREENER_UNIVERSE", "")
    universe = tuple(parse_symbols(raw_universe)) if raw_universe else DEFAULT_CRYPTO_UNIVERSE
    raw_seed = env_str(env, "SCREENER_SEED_SYMBOLS", DEFAULT_SCREENER_SEED_SYMBOLS)
    seed_symbols = tuple(parse_symbols(raw_seed))
    raw_exclude = env_str(env, "SCREENER_EXCLUDE_SYMBOLS", "")
    exclude_symbols = tuple(parse_symbols(raw_exclude)) if raw_exclude else ()
    return ScreenerSettings(
        enabled=env_bool(env, "USE_SCREENER", False),
        universe=universe,
        seed_symbols=seed_symbols,
        exclude_symbols=exclude_symbols,
        exclude_leveraged_etfs=env_bool(env, "SCREENER_EXCLUDE_LEVERAGED_ETFS", True),
        exclude_large_caps=env_bool(env, "SCREENER_EXCLUDE_LARGE_CAPS", False),
        movers_only=env_bool(env, "SCREENER_MOVERS_ONLY", False),
        fallback_to_static_symbols=env_bool(env, "SCREENER_FALLBACK_TO_STATIC", True),
        merge_seed_with_movers=env_bool(env, "SCREENER_MERGE_SEED_WITH_MOVERS", True),
        timeframe=env_str(env, "SCREENER_TIMEFRAME", "15Min"),
        bar_limit=env_int(env, "SCREENER_BAR_LIMIT", 50),
        atr_period=env_int(env, "SCREENER_ATR_PERIOD", 14),
        lookback=env_int(env, "SCREENER_LOOKBACK", 20),
        refresh_seconds=env_int(env, "SCREENER_REFRESH_SECONDS", 900),
        am_refresh_seconds=env_int(env, "SCREENER_AM_REFRESH_SECONDS", 0),
        min_price=env_float(env, "SCREENER_MIN_PRICE", 5.0),
        max_price=env_float(env, "SCREENER_MAX_PRICE", float("inf")),
        min_dollar_volume=env_float(env, "SCREENER_MIN_DOLLAR_VOLUME", 250_000.0),
        min_atr_pct=env_float(env, "SCREENER_MIN_ATR_PCT", 0.004),
        max_atr_pct=env_float(env, "SCREENER_MAX_ATR_PCT", 1.0),
        min_change_pct=env_float(env, "SCREENER_MIN_CHANGE_PCT", 0.0),
        min_bars=env_int(env, "SCREENER_MIN_BARS", 10),
        top_n=env_int(env, "SCREENER_TOP_N", 5),
        weight_volatility=env_float(env, "SCREENER_WEIGHT_VOLATILITY", 1.2),
        weight_liquidity=env_float(env, "SCREENER_WEIGHT_LIQUIDITY", 1.0),
        weight_momentum=env_float(env, "SCREENER_WEIGHT_MOMENTUM", 0.0),
        use_movers=env_bool(env, "SCREENER_USE_MOVERS", False),
        movers_source=env_str(env, "SCREENER_MOVERS_SOURCE", "actives"),
        movers_top=env_int(env, "SCREENER_MOVERS_TOP", 25),
        movers_min_volume=env_float(env, "SCREENER_MOVERS_MIN_VOLUME", 100_000.0),
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


def _load_workhorse(env: Mapping[str, str]) -> WorkhorseSettings:
    return WorkhorseSettings(
        provider=env_str(env, "RESEARCH_WORKHORSE_PROVIDER", "none").strip().lower(),
        openai_api_key=env_str(env, "OPENAI_API_KEY", ""),
        openai_model=env_str(env, "OPENAI_MODEL", "gpt-4o-mini"),
        xai_api_key=env_str(env, "XAI_API_KEY", ""),
        xai_model=env_str(env, "XAI_MODEL", "grok-4.3"),
        min_interval_seconds=env_int(env, "RESEARCH_WORKHORSE_INTERVAL_SECONDS", 900),
        max_calls_per_day=env_int(env, "RESEARCH_WORKHORSE_MAX_CALLS_PER_DAY", 16),
        max_tokens=env_int(env, "RESEARCH_WORKHORSE_MAX_TOKENS", 2048),
        timeout_seconds=env_float(env, "RESEARCH_WORKHORSE_TIMEOUT_SECONDS", 60.0),
    )


def _load_premium(env: Mapping[str, str]) -> PremiumSettings:
    return PremiumSettings(
        provider=env_str(env, "RESEARCH_PREMIUM_PROVIDER", "none").strip().lower(),
        openai_model=env_str(env, "RESEARCH_PREMIUM_OPENAI_MODEL", "gpt-4o"),
        xai_model=env_str(env, "RESEARCH_PREMIUM_XAI_MODEL", "grok-4.3"),
        min_interval_seconds=env_int(env, "RESEARCH_PREMIUM_INTERVAL_SECONDS", 1800),
        max_calls_per_day=env_int(env, "RESEARCH_PREMIUM_MAX_CALLS_PER_DAY", 4),
        max_tokens=env_int(env, "RESEARCH_PREMIUM_MAX_TOKENS", 2048),
        timeout_seconds=env_float(env, "RESEARCH_PREMIUM_TIMEOUT_SECONDS", 90.0),
    )


def _load_research(env: Mapping[str, str]) -> ResearchSettings:
    claude_enabled = env_bool(env, "ENABLE_CLAUDE", False)
    workhorse = _load_workhorse(env)
    premium = _load_premium(env)
    any_tier = (
        claude_enabled
        or workhorse.is_active
        or (premium.is_active and not claude_enabled)
    )
    enabled = env_bool(env, "ENABLE_RESEARCH", any_tier) and any_tier
    return ResearchSettings(
        enabled=enabled,
        claude_enabled=claude_enabled,
        tier_mode=env_str(env, "RESEARCH_TIER_MODE", "both").strip().lower(),
        api_key=env_str(env, "ANTHROPIC_API_KEY", ""),
        model=env_str(env, "CLAUDE_MODEL", "claude-sonnet-4-20250514"),
        workhorse=workhorse,
        premium=premium,
        brief_file=env_str(env, "RESEARCH_BRIEF_FILE", "logs/research_brief.json"),
        max_tokens=env_int(env, "CLAUDE_MAX_TOKENS", 4096),
        timeout_seconds=env_float(env, "CLAUDE_TIMEOUT_SECONDS", 60.0),
        max_ideas_per_cycle=env_int(env, "CLAUDE_MAX_IDEAS", 5),
        min_confidence=env_float(env, "CLAUDE_MIN_CONFIDENCE", 0.55),
        entry_veto_min_confidence=env_float(env, "RESEARCH_ENTRY_VETO_MIN_CONFIDENCE", 0.10),
        min_interval_seconds=env_int(env, "CLAUDE_CALL_INTERVAL_SECONDS", 300),
        max_calls_per_day=env_int(env, "CLAUDE_MAX_CALLS_PER_DAY", 100),
        require_approval_for_entry=env_bool(env, "CLAUDE_REQUIRE_APPROVAL", True),
        block_avoid_for_entry=env_bool(env, "RESEARCH_BLOCK_AVOID", True),
        block_hold_for_entry=env_bool(env, "RESEARCH_BLOCK_HOLD", True),
        equities_only=env_bool(env, "CLAUDE_EQUITIES_ONLY", True),
        memory_file=env_str(env, "CLAUDE_MEMORY_FILE", "logs/research_memory.json"),
        memory_max_reflections=env_int(env, "CLAUDE_MEMORY_MAX_REFLECTIONS", 100),
        knowledge_file=env_str(env, "TRADE_KNOWLEDGE_FILE", "logs/trade_knowledge.json"),
        knowledge_max_records=env_int(env, "TRADE_KNOWLEDGE_MAX_RECORDS", 10_000),
        performance_window=env_int(env, "CLAUDE_PERFORMANCE_WINDOW", 20),
        evaluation_file=env_str(env, "CLAUDE_EVALUATION_FILE", "logs/research_evaluation.json"),
        evaluation_max_records=env_int(env, "CLAUDE_EVALUATION_MAX_RECORDS", 500),
        postmortem_enabled=env_bool(env, "CLAUDE_POSTMORTEM_ENABLED", False),
        postmortem_max_per_day=env_int(env, "CLAUDE_POSTMORTEM_MAX_PER_DAY", 1),
        market_hours_only=env_bool(env, "CLAUDE_MARKET_HOURS_ONLY", True),
        billing_cooldown_seconds=env_int(env, "CLAUDE_BILLING_COOLDOWN_SECONDS", 3600),
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

    asset_class = env_str(env, "ASSET_CLASS", ASSET_CLASS_CRYPTO).strip().lower()
    if asset_class == ASSET_CLASS_EQUITIES:
        symbols = tuple(parse_symbols(env_str(env, "EQUITY_SYMBOLS", DEFAULT_EQUITY_SYMBOLS)))
        fallback = tuple(parse_symbols(DEFAULT_EQUITY_SYMBOLS))
    else:
        symbols = tuple(parse_symbols(env_str(env, "CRYPTO_SYMBOLS", DEFAULT_CRYPTO_SYMBOL)))
        fallback = (DEFAULT_CRYPTO_SYMBOL,)
    if not symbols:
        symbols = fallback

    settings = Settings(
        alpaca=_load_alpaca(env),
        risk=_load_risk(env),
        strategy=_load_strategy(env),
        runtime=_load_runtime(env),
        screener=_load_screener(env),
        research=_load_research(env),
        asset_class=asset_class,
        crypto_mode=env_bool(env, "CRYPTO_MODE", asset_class == ASSET_CLASS_CRYPTO),
        symbols=symbols,
    )
    settings.validate()
    return settings
