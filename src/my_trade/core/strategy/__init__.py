"""Strategy engine (deterministic, pure).

Phase 1 migration target for the prototype's `strategy.py`.

Contract: given clean DataFrames (1m/5m/15m), compute indicators and return a
typed `Signal | None` plus a structured `ScanEvaluation` (reasons/failures).
No network calls; inject the clock for testability. Shared by backtest AND live.
"""

from .indicators import add_indicators, extract_snapshot, opt_float, rolling_vwap
from .models import (
    BarSnapshot,
    OrderSide,
    ScanEvaluation,
    Signal,
    StrategyParams,
)
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
    is_near_signal,
)
from .strategy import PullbackStrategy

__all__ = [
    "BarSnapshot",
    "ConditionResult",
    "OrderSide",
    "PullbackStrategy",
    "ScanEvaluation",
    "Signal",
    "StrategyParams",
    "add_indicators",
    "build_signal",
    "check_bollinger",
    "check_macd",
    "check_rsi",
    "check_trend",
    "check_volume",
    "check_vwap",
    "decide_exit",
    "evaluate_conditions",
    "extract_snapshot",
    "is_near_signal",
    "opt_float",
    "rolling_vwap",
]
