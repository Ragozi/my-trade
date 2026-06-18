"""Strategy orchestrator: wires pandas indicators to pure decision logic.

This class performs no I/O and no logging — it is deterministic given its bar
inputs and an explicit ``now`` timestamp, so it behaves identically in live and
backtest. All *decisions* are delegated to ``signals.py``.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from .indicators import add_indicators, extract_snapshot, opt_float
from .models import ScanEvaluation, Signal, StrategyParams
from .signals import (
    ConditionResult,
    build_signal,
    check_bollinger,
    check_macd,
    check_rsi,
    check_trend,
    check_volume,
    check_vwap,
    decide_exit,
    evaluate_conditions,
)


class PullbackStrategy:
    """v3 BTC long pullback scalper (VWAP + RSI + MACD + Bollinger)."""

    def __init__(self, params: StrategyParams | None = None) -> None:
        self._p = params or StrategyParams()

    @property
    def params(self) -> StrategyParams:
        return self._p

    def _trend_result(self, df: pd.DataFrame, label: str) -> ConditionResult:
        if df.empty:
            return ConditionResult(False, f"{label}: no data")
        enriched = add_indicators(df, self._p)
        row = enriched.iloc[-1]
        ema = opt_float(row.get("ema_trend"))
        return check_trend(float(row["close"]), ema, label)

    def detect_entry(
        self,
        symbol: str,
        df_1m: pd.DataFrame,
        df_5m: pd.DataFrame,
        df_15m: pd.DataFrame,
        now: datetime | None = None,
    ) -> tuple[Signal | None, ScanEvaluation]:
        results: list[ConditionResult] = []

        if self._p.require_5m_uptrend:
            results.append(self._trend_result(df_5m, "5m"))
        if self._p.require_15m_uptrend:
            results.append(self._trend_result(df_15m, "15m"))

        enriched = add_indicators(df_1m, self._p)
        snapshot = extract_snapshot(enriched)
        if snapshot is None:
            results.append(ConditionResult(False, "1m insufficient bars"))
            return None, evaluate_conditions(results)

        results.extend(
            [
                check_vwap(snapshot.close, snapshot.vwap, self._p),
                check_rsi(snapshot.rsi, snapshot.rsi_prev, self._p),
                check_macd(snapshot.macd_hist, snapshot.macd_hist_prev, self._p),
                check_bollinger(snapshot.close, snapshot.bb_lower, snapshot.bb_mid, self._p),
                check_volume(snapshot, self._p),
            ]
        )

        evaluation = evaluate_conditions(results)
        if not evaluation.eligible:
            return None, evaluation

        signal = build_signal(symbol, snapshot.close, self._p, evaluation.passes, now)
        return signal, evaluation

    def detect_exit(
        self,
        df_1m: pd.DataFrame,
        entry_time: datetime,
        entry_price: float,
        now: datetime,
    ) -> str | None:
        if df_1m.empty:
            return None
        enriched = add_indicators(df_1m, self._p)
        row = enriched.iloc[-1]
        rsi = opt_float(row.get("rsi"))
        hold_minutes = (now - entry_time).total_seconds() / 60.0
        return decide_exit(
            last_low=float(row["low"]),
            last_high=float(row["high"]),
            rsi=rsi,
            hold_minutes=hold_minutes,
            entry_price=entry_price,
            params=self._p,
        )
