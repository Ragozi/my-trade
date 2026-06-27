"""Tests for API serializers and env patching."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi import HTTPException

import my_trade.api.app as api_app
from my_trade.api.env_patch import merge_env_lines, patch_to_env_updates, resolve_symbol_key
from my_trade.api.serializers import stats_from_events
from my_trade.config import load_settings
from my_trade.core.monitoring.state import DailyState
from my_trade.observability.journal import JournalEvent


class TestEnvPatch:
    def test_patch_maps_nested_fields(self) -> None:
        updates = patch_to_env_updates(
            {
                "asset_class": "equities",
                "screener": {"enabled": True, "top_n": 3},
                "risk": {"max_risk_per_trade_pct": 0.02},
            }
        )
        assert updates["ASSET_CLASS"] == "equities"
        assert updates["USE_SCREENER"] == "true"
        assert updates["SCREENER_TOP_N"] == "3"
        assert updates["MAX_RISK_PER_TRADE_PCT"] == "0.02"

    def test_symbols_resolve_by_asset_class(self) -> None:
        updates = patch_to_env_updates({"symbols": ["AAPL", "MSFT"]})
        resolved = resolve_symbol_key(updates, "equities")
        assert resolved["EQUITY_SYMBOLS"] == "AAPL,MSFT"
        assert "CRYPTO_SYMBOLS" not in resolved

    def test_merge_env_replaces_existing_key(self) -> None:
        text = "ASSET_CLASS=crypto\nPAPER_TRADING=true\n"
        out = merge_env_lines(text, {"ASSET_CLASS": "equities"})
        assert "ASSET_CLASS=equities" in out
        assert "PAPER_TRADING=true" in out

    def test_rejects_env_value_line_injection(self) -> None:
        with pytest.raises(ValueError):
            patch_to_env_updates(
                {
                    "risk": {
                        "max_risk_per_trade_pct": (
                            "0.02\nALLOW_LIVE_TRADING=true\nPAPER_TRADING=false"
                        )
                    }
                }
            )

    def test_merge_env_rejects_direct_injection(self) -> None:
        with pytest.raises(ValueError):
            merge_env_lines(
                "MAX_RISK_PER_TRADE_PCT=0.01\n",
                {"MAX_RISK_PER_TRADE_PCT": "0.02\nALLOW_LIVE_TRADING=true"},
            )


class TestApiSafety:
    def test_paper_runner_guard_rejects_live_mode(self) -> None:
        settings = load_settings(
            env={
                "APCA_API_KEY_ID": "key",
                "APCA_API_SECRET_KEY": "secret",
                "PAPER_TRADING": "false",
                "ALLOW_LIVE_TRADING": "true",
            }
        )

        class Helpers:
            ALLOW_LIVE = False

        with pytest.raises(HTTPException) as exc:
            api_app._require_paper_runner_settings(settings, Helpers())

        assert exc.value.status_code == 400
        assert "PAPER_TRADING=true" in exc.value.detail


class TestSerializers:
    def test_stats_counts_today_events(self) -> None:
        events = [
            JournalEvent("2026-06-19T10:00:00", "entry_submitted", "BTC/USD", "", 100.0, 0.0),
            JournalEvent("2026-06-19T11:00:00", "halt", "", "circuit_breaker", 99.0, -1.0),
            JournalEvent("2026-06-18T12:00:00", "entry_submitted", "ETH/USD", "", 100.0, 0.0),
        ]
        state = DailyState(
            trading_day=date(2026, 6, 19),
            start_of_day_equity=100_000.0,
            peak_equity=101_000.0,
            entries_today={"BTCUSD": 1},
        )
        stats = stats_from_events(events, state, (100.0, 0.0), today=date(2026, 6, 19))
        assert stats["today"]["entries"] == 1
        assert stats["today"]["halts"] == 1
        assert stats["daily_state"]["peak_equity"] == 101_000.0

    def test_settings_to_config_shape(self) -> None:
        from my_trade.api.serializers import settings_to_config

        cfg = settings_to_config(load_settings(env={}))
        assert cfg["asset_class"] == "crypto"
        assert "screener" in cfg
        assert "risk" in cfg
        assert cfg["risk"]["max_open_risk_pct"] == cfg["risk"]["max_open_risk_pct"]
