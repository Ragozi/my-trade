"""Serialize deterministic strategy scans for the research layer."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol


class StrategyScanner(Protocol):
    def detect_entry(
        self,
        symbol: str,
        df_1m: object,
        df_5m: object,
        df_15m: object,
        now: datetime | None = None,
    ) -> tuple[object | None, object]: ...


class BarLoader(Protocol):
    def __call__(self, symbol: str, timeframe: str) -> object: ...


def gather_technical_scans(
    *,
    symbols: tuple[str, ...],
    strategy: StrategyScanner,
    get_bars: BarLoader,
    entry_tf: str,
    trend_tf: str,
    trend_tf_15m: str,
    when: datetime,
) -> tuple[dict[str, Any], ...]:
    """Run the pullback strategy evaluator on each candidate (no orders)."""
    out: list[dict[str, Any]] = []
    for symbol in symbols:
        try:
            signal, evaluation = strategy.detect_entry(
                symbol,
                get_bars(symbol, entry_tf),
                get_bars(symbol, trend_tf),
                get_bars(symbol, trend_tf_15m),
                when,
            )
            out.append(
                {
                    "symbol": symbol.upper(),
                    "strategy_signal": signal is not None,
                    "eligible": bool(getattr(evaluation, "eligible", False)),
                    "near_signal": bool(getattr(evaluation, "near_signal", False)),
                    "summary": str(getattr(evaluation, "summary", "") or ""),
                    "passes": list(getattr(evaluation, "passes", ()) or ()),
                    "failures": list(getattr(evaluation, "failures", ()) or ()),
                }
            )
        except Exception as exc:
            out.append(
                {
                    "symbol": symbol.upper(),
                    "strategy_signal": False,
                    "eligible": False,
                    "near_signal": False,
                    "summary": f"scan error: {exc}",
                    "passes": [],
                    "failures": ["scan_error"],
                }
            )
    return tuple(out)
