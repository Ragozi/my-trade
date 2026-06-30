"""Tests for API serializers and env patching."""

from __future__ import annotations

import importlib
from datetime import date
from types import SimpleNamespace

from fastapi.testclient import TestClient

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


class TestBotApi:
    def test_once_rejects_when_bot_is_running(self, monkeypatch, tmp_path) -> None:
        api_app = importlib.import_module("my_trade.api.app")
        settings = SimpleNamespace(runtime=SimpleNamespace(log_dir=str(tmp_path)))
        status = SimpleNamespace(running=True, pid=1234, last_cycle_at=None)

        class PaperHelpers:
            def run_once(self, _settings) -> int:
                raise AssertionError("run_once should not be called while bot is running")

        monkeypatch.setattr(api_app, "load_settings", lambda: settings)
        monkeypatch.setattr(api_app, "get_bot_status", lambda _log_dir: status)
        monkeypatch.setattr(api_app, "_paper_helpers", lambda: PaperHelpers())

        response = TestClient(api_app.create_app()).post("/api/bot/once")

        assert response.status_code == 409
        assert "Bot already running" in response.json()["detail"]

    def test_once_rejects_when_another_bot_operation_is_active(self) -> None:
        api_app = importlib.import_module("my_trade.api.app")
        assert api_app._BOT_OPERATION_LOCK.acquire(blocking=False)
        try:
            response = TestClient(api_app.create_app()).post("/api/bot/once")
        finally:
            api_app._BOT_OPERATION_LOCK.release()

        assert response.status_code == 409
        assert response.json()["detail"] == "Another bot operation is already in progress"
