"""Tests for research technical scan assembly."""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from my_trade.core.strategy import PullbackStrategy, StrategyParams
from my_trade.research.technical import gather_technical_scans


def _empty_bars() -> pd.DataFrame:
    return pd.DataFrame()


def test_gather_technical_scans_returns_per_symbol() -> None:
    strategy = PullbackStrategy(StrategyParams(crypto_mode=False, require_15m_uptrend=False))
    scans = gather_technical_scans(
        symbols=("NVDA", "AMD"),
        strategy=strategy,
        get_bars=lambda _s, _tf: _empty_bars(),
        entry_tf="1Min",
        trend_tf="5Min",
        trend_tf_15m="15Min",
        when=datetime(2026, 7, 7, 14, 0, tzinfo=UTC),
    )
    assert len(scans) == 2
    assert scans[0]["symbol"] == "NVDA"
    assert "summary" in scans[0]
    assert "failures" in scans[0]
