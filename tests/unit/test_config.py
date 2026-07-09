"""Tests for the typed config layer (pure, no real environment needed)."""

from __future__ import annotations

import pytest

from my_trade.config import (
    DEFAULT_CRYPTO_SYMBOL,
    RiskSettings,
    Settings,
    load_settings,
)
from my_trade.config.parsing import (
    env_bool,
    env_float,
    env_int,
    env_str,
    parse_symbols,
)
from my_trade.core.risk import RiskLimits


class TestParsing:
    def test_env_str_default_and_value(self) -> None:
        assert env_str({}, "K", "fallback") == "fallback"
        assert env_str({"K": "v"}, "K", "fallback") == "v"

    @pytest.mark.parametrize("raw", ["1", "true", "YES", "On", "t"])
    def test_env_bool_truthy(self, raw: str) -> None:
        assert env_bool({"K": raw}, "K", False) is True

    @pytest.mark.parametrize("raw", ["0", "false", "NO", "off", ""])
    def test_env_bool_falsy(self, raw: str) -> None:
        assert env_bool({"K": raw}, "K", True) is False

    def test_env_bool_default_when_missing(self) -> None:
        assert env_bool({}, "K", True) is True

    def test_env_bool_invalid_raises(self) -> None:
        with pytest.raises(ValueError):
            env_bool({"K": "maybe"}, "K", False)

    def test_env_int_and_float(self) -> None:
        assert env_int({"K": "42"}, "K", 0) == 42
        assert env_int({}, "K", 7) == 7
        assert env_float({"K": "0.5"}, "K", 0.0) == 0.5

    def test_env_int_invalid_raises(self) -> None:
        with pytest.raises(ValueError):
            env_int({"K": "3.5"}, "K", 0)

    def test_env_float_invalid_raises(self) -> None:
        with pytest.raises(ValueError):
            env_float({"K": "abc"}, "K", 0.0)

    def test_parse_symbols_dedupes_and_uppercases(self) -> None:
        assert parse_symbols("btc/usd, eth/usd ,BTC/USD") == ["BTC/USD", "ETH/USD"]

    def test_parse_symbols_empty(self) -> None:
        assert parse_symbols("  ,  ") == []


class TestRiskSettings:
    def test_to_limits_round_trips_values(self) -> None:
        rs = RiskSettings()
        limits = rs.to_limits()
        assert isinstance(limits, RiskLimits)
        assert limits.max_risk_per_trade_pct == pytest.approx(0.02)
        assert limits.max_total_open_risk_pct == pytest.approx(0.07)
        assert limits.daily_loss_limit_pct == pytest.approx(0.05)
        assert limits.max_drawdown_pct == pytest.approx(0.15)
        assert limits.max_concurrent_positions == 1

    def test_validate_rejects_pct_out_of_range(self) -> None:
        with pytest.raises(ValueError):
            RiskSettings(max_risk_per_trade_pct=0.0).validate()
        with pytest.raises(ValueError):
            RiskSettings(daily_loss_limit_pct=1.5).validate()

    def test_validate_rejects_per_trade_exceeding_open_risk(self) -> None:
        with pytest.raises(ValueError):
            RiskSettings(max_risk_per_trade_pct=0.10, max_total_open_risk_pct=0.07).validate()

    def test_validate_rejects_zero_positions(self) -> None:
        with pytest.raises(ValueError):
            RiskSettings(max_concurrent_positions=0).validate()


class TestLoadSettings:
    def test_defaults_with_empty_env(self) -> None:
        s = load_settings(env={})
        assert isinstance(s, Settings)
        assert s.crypto_mode is True
        assert s.symbols == (DEFAULT_CRYPTO_SYMBOL,)
        assert s.alpaca.paper_trading is True
        assert s.alpaca.allow_live_trading is False
        assert s.risk.max_risk_per_trade_pct == pytest.approx(0.02)

    def test_reads_overrides_from_mapping(self) -> None:
        env = {
            "APCA_API_KEY_ID": "key",
            "APCA_API_SECRET_KEY": "secret",
            "MAX_RISK_PER_TRADE_PCT": "0.01",
            "CRYPTO_SYMBOLS": "eth/usd, btc/usd",
            "SCAN_INTERVAL_SECONDS": "30",
            "REQUIRE_15M_UPTREND": "false",
        }
        s = load_settings(env=env)
        assert s.alpaca.api_key == "key"
        assert s.risk.max_risk_per_trade_pct == pytest.approx(0.01)
        assert s.symbols == ("ETH/USD", "BTC/USD")
        assert s.runtime.scan_interval_seconds == 30
        assert s.strategy.require_15m_uptrend is False

    def test_empty_symbols_fall_back_to_default(self) -> None:
        s = load_settings(env={"CRYPTO_SYMBOLS": "  , "})
        assert s.symbols == (DEFAULT_CRYPTO_SYMBOL,)

    def test_invalid_risk_value_fails_fast(self) -> None:
        with pytest.raises(ValueError):
            load_settings(env={"MAX_RISK_PER_TRADE_PCT": "2"})  # 200% > 1.0

    def test_validate_for_trading_requires_keys(self) -> None:
        s = load_settings(env={})
        with pytest.raises(ValueError):
            s.validate_for_trading()

    def test_validate_for_trading_blocks_live_without_both_flags(self) -> None:
        env = {
            "APCA_API_KEY_ID": "key",
            "APCA_API_SECRET_KEY": "secret",
            "PAPER_TRADING": "false",
            "ALLOW_LIVE_TRADING": "false",
        }
        s = load_settings(env=env)
        with pytest.raises(ValueError):
            s.validate_for_trading()

    def test_validate_for_trading_allows_paper(self) -> None:
        env = {"APCA_API_KEY_ID": "key", "APCA_API_SECRET_KEY": "secret"}
        s = load_settings(env=env)
        s.validate_for_trading()  # should not raise


class TestAssetClass:
    def test_defaults_to_crypto(self) -> None:
        s = load_settings(env={})
        assert s.asset_class == "crypto"
        assert s.is_equities is False
        assert s.symbols == (DEFAULT_CRYPTO_SYMBOL,)

    def test_equities_uses_equity_symbol_defaults(self) -> None:
        s = load_settings(env={"ASSET_CLASS": "equities"})
        assert s.is_equities is True
        assert s.crypto_mode is False
        assert "AAPL" in s.symbols

    def test_equities_reads_equity_symbols(self) -> None:
        s = load_settings(env={"ASSET_CLASS": "EQUITIES", "EQUITY_SYMBOLS": "spy, qqq"})
        assert s.asset_class == "equities"
        assert s.symbols == ("SPY", "QQQ")

    def test_equities_empty_symbols_fall_back(self) -> None:
        s = load_settings(env={"ASSET_CLASS": "equities", "EQUITY_SYMBOLS": " , "})
        assert "AAPL" in s.symbols

    def test_movers_only_allows_empty_equity_symbols(self) -> None:
        s = load_settings(
            env={
                "ASSET_CLASS": "equities",
                "EQUITY_SYMBOLS": "",
                "USE_SCREENER": "true",
                "SCREENER_USE_MOVERS": "true",
                "SCREENER_MOVERS_ONLY": "true",
                "SCREENER_FALLBACK_TO_STATIC": "false",
            }
        )
        assert s.symbols == ()
        assert s.screener.movers_only is True
        s.validate()  # must not require static symbols

    def test_retired_claude_model_rejected_for_trading(self) -> None:
        env = {
            "APCA_API_KEY_ID": "key",
            "APCA_API_SECRET_KEY": "secret",
            "ENABLE_CLAUDE": "true",
            "ANTHROPIC_API_KEY": "sk-test",
            "CLAUDE_MODEL": "claude-sonnet-4-20250514",
        }
        s = load_settings(env=env)
        with pytest.raises(ValueError, match="retired"):
            s.validate_for_trading()

    def test_invalid_asset_class_fails_fast(self) -> None:
        with pytest.raises(ValueError):
            load_settings(env={"ASSET_CLASS": "forex"})

    def test_screener_movers_settings_loaded(self) -> None:
        env = {
            "USE_SCREENER": "true",
            "SCREENER_USE_MOVERS": "true",
            "SCREENER_MOVERS_SOURCE": "gainers",
            "SCREENER_MOVERS_TOP": "15",
            "SCREENER_MOVERS_MIN_VOLUME": "100000",
        }
        s = load_settings(env=env)
        assert s.screener.use_movers is True
        assert s.screener.movers_source == "gainers"
        assert s.screener.movers_top == 15
        assert s.screener.movers_min_volume == pytest.approx(100000.0)

    def test_screener_seed_and_merge_defaults(self) -> None:
        s = load_settings(env={"USE_SCREENER": "true"})
        assert "NVDA" in s.screener.seed_symbols
        assert "SYM" in s.screener.seed_symbols
        assert s.screener.merge_seed_with_movers is True
        assert s.screener.exclude_leveraged_etfs is True
        assert s.screener.min_price == pytest.approx(5.0)
