"""Indicator + orchestrator smoke tests (these touch pandas/pandas_ta)."""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from my_trade.core.strategy import (
    PullbackStrategy,
    StrategyParams,
    add_indicators,
    extract_snapshot,
)


def _frame(closes: list[float], volume: float = 1000.0) -> pd.DataFrame:
    start = datetime(2026, 1, 1, 12, 0)
    rows = [
        {
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": volume,
        }
        for close in closes
    ]
    idx = [start + timedelta(minutes=i) for i in range(len(closes))]
    return pd.DataFrame(rows, index=pd.DatetimeIndex(idx))


class TestIndicators:
    def test_add_indicators_creates_columns(self) -> None:
        df = _frame([100.0 + i for i in range(60)])
        out = add_indicators(df, StrategyParams())
        for col in ("ema_trend", "rsi", "vol_sma", "vwap", "macd_hist", "bb_lower", "bb_mid"):
            assert col in out.columns

    def test_add_indicators_empty_passthrough(self) -> None:
        empty = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        assert add_indicators(empty, StrategyParams()).empty

    def test_extract_snapshot_none_when_too_short(self) -> None:
        df = add_indicators(_frame([100.0]), StrategyParams())
        assert extract_snapshot(df) is None

    def test_extract_snapshot_populated(self) -> None:
        df = add_indicators(_frame([100.0 + i for i in range(60)]), StrategyParams())
        snap = extract_snapshot(df)
        assert snap is not None
        assert snap.close == 159.0
        assert snap.rsi is not None  # enough bars for RSI(14)


class TestOrchestrator:
    def test_insufficient_bars_not_eligible(self) -> None:
        strat = PullbackStrategy(StrategyParams(require_15m_uptrend=False))
        signal, ev = strat.detect_entry("BTC/USD", _frame([100.0]), _frame([]), _frame([]))
        assert signal is None
        assert ev.eligible is False
        assert any("insufficient" in f for f in ev.failures)

    def test_15m_uptrend_failure_surfaces(self) -> None:
        strat = PullbackStrategy(StrategyParams(require_15m_uptrend=True))
        # Falling 15m series -> close below EMA -> trend fails.
        df15 = _frame([200.0 - i for i in range(60)])
        df1 = _frame([100.0 + i for i in range(60)])
        signal, ev = strat.detect_entry("BTC/USD", df1, _frame([]), df15)
        assert signal is None
        assert ev.eligible is False
        assert any("15m" in f for f in ev.failures)

    def test_eligible_signal_on_constructed_pullback(self) -> None:
        # Disable optional filters; allow RSI/VWAP to pass by widening them so
        # the wiring (indicators -> snapshot -> decision -> signal) is exercised
        # end-to-end on an accelerating-up series (MACD hist > 0 and expanding).
        params = StrategyParams(
            require_5m_uptrend=False,
            require_15m_uptrend=False,
            require_rsi_turning_up=False,
            require_volume_spike=False,
            bollinger_lower_half_only=False,
            rsi_oversold=100.0,        # RSI always <= 100 -> passes
            vwap_pullback_pct=1.0,     # 100% tolerance -> VWAP always passes
        )
        strat = PullbackStrategy(params)
        closes = [100.0 + i * 0.5 + (i * i) * 0.01 for i in range(80)]
        signal, ev = strat.detect_entry("BTC/USD", _frame(closes), _frame([]), _frame([]))
        assert ev.eligible is True
        assert signal is not None
        assert signal.stop_price < signal.entry_price < signal.take_profit_price

    def test_detect_exit_time_stop(self) -> None:
        strat = PullbackStrategy(StrategyParams())
        df = _frame([100.0 + i for i in range(20)])
        entry_time = datetime(2026, 1, 1, 12, 0)
        now = entry_time + timedelta(minutes=30)  # > max_hold 15
        assert strat.detect_exit(df, entry_time, 100.0, now) == "time_stop"

    def test_detect_exit_stop_loss(self) -> None:
        strat = PullbackStrategy(StrategyParams())
        entry = 100.0
        # Flat series -> RSI is neutral/NaN, so the stop (not RSI) drives the exit.
        df = _frame([100.0] * 20)
        # Force last bar low below the stop.
        stop = entry * (1 - StrategyParams().stop_loss_pct)
        df.iloc[-1, df.columns.get_loc("low")] = stop - 1.0
        entry_time = datetime(2026, 1, 1, 12, 0)
        now = entry_time + timedelta(minutes=5)
        assert strat.detect_exit(df, entry_time, entry, now) == "stop_loss"

    def test_detect_exit_empty_returns_none(self) -> None:
        strat = PullbackStrategy(StrategyParams())
        empty = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        now = datetime(2026, 1, 1, 12, 30)
        assert strat.detect_exit(empty, datetime(2026, 1, 1, 12, 0), 100.0, now) is None


def test_params_from_settings_maps_fields() -> None:
    from my_trade.config import load_settings

    settings = load_settings(env={"VWAP_PULLBACK_PCT": "0.02", "CRYPTO_MODE": "true"})
    params = StrategyParams.from_settings(settings)
    assert params.vwap_pullback_pct == 0.02
    assert params.crypto_mode is True
    assert isinstance(params, StrategyParams)
