"""Regression tests for paper runner operator paths."""

from __future__ import annotations

import pandas as pd

from my_trade.config import load_settings
from my_trade.core.monitoring.account import AccountSnapshot
from scripts.paper_trade import Providers, run_health_checks


class FakeData:
    def __init__(self) -> None:
        self.symbols: list[str] = []

    def get_bars(
        self, symbol: str, timeframe: str, limit: int | None = None
    ) -> pd.DataFrame:
        self.symbols.append(symbol)
        return pd.DataFrame({"close": [100.0]})


class FakeAccount:
    def get_snapshot(self) -> AccountSnapshot:
        return AccountSnapshot(equity=100_000.0, cash=100_000.0)


class FakeBroker:
    def list_open_orders(self) -> list[object]:
        return []


def test_health_check_uses_probe_symbol_for_movers_only_config() -> None:
    settings = load_settings(
        env={
            "ASSET_CLASS": "equities",
            "EQUITY_SYMBOLS": "",
            "USE_SCREENER": "true",
            "SCREENER_USE_MOVERS": "true",
            "SCREENER_MOVERS_ONLY": "true",
            "SCREENER_FALLBACK_TO_STATIC": "false",
        }
    )
    data = FakeData()

    ok = run_health_checks(settings, Providers(data=data, account=FakeAccount(), broker=FakeBroker()))

    assert ok is True
    assert settings.symbols == ()
    assert data.symbols == ["AAPL"]
