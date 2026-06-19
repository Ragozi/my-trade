"""Pure metric computation for the screener (pandas in, scalars out).

This is the only screening module that touches pandas. It turns a cleaned OHLCV
frame into a :class:`Candidate`. It is intentionally independent of pandas_ta and
of the strategy layer so the screener stays fast and cheap to run across a wide
universe. It makes no selection decisions — that lives in ``filters.py``.
"""

from __future__ import annotations

import pandas as pd

from .models import Candidate


def average_true_range(df: pd.DataFrame, period: int) -> float | None:
    """Wilder-style simple-mean ATR over the last ``period`` bars.

    Returns ``None`` when there are too few bars to compute it.
    """
    if df.empty or len(df) < period + 1:
        return None
    high = df["high"]
    low = df["low"]
    prev_close = df["close"].shift(1)
    true_range = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    atr = float(true_range.tail(period).mean())
    return atr


def atr_pct(df: pd.DataFrame, period: int) -> float | None:
    """ATR expressed as a fraction of the latest close."""
    atr = average_true_range(df, period)
    if atr is None:
        return None
    last_close = float(df["close"].iloc[-1])
    if last_close <= 0:
        return None
    return atr / last_close


def avg_dollar_volume(df: pd.DataFrame, lookback: int) -> float:
    """Mean per-bar dollar volume (``close * volume``) over the last ``lookback`` bars."""
    if df.empty:
        return 0.0
    window = df.tail(lookback)
    dollar = window["close"] * window["volume"]
    return float(dollar.mean())


def change_pct(df: pd.DataFrame, lookback: int) -> float:
    """Fractional change between the close ``lookback`` bars ago and the latest close."""
    if df.empty or len(df) < 2:
        return 0.0
    span = min(lookback, len(df) - 1)
    start = float(df["close"].iloc[-1 - span])
    end = float(df["close"].iloc[-1])
    if start <= 0:
        return 0.0
    return (end - start) / start


def build_candidate(
    symbol: str,
    df: pd.DataFrame,
    *,
    atr_period: int = 14,
    lookback: int = 20,
) -> Candidate | None:
    """Summarize a symbol's recent bars into a :class:`Candidate`.

    Returns ``None`` when there is not enough data to compute a meaningful ATR
    (the screener treats that as "skip this symbol", never a crash).
    """
    if df.empty or len(df) < atr_period + 1:
        return None
    pct = atr_pct(df, atr_period)
    if pct is None:
        return None
    return Candidate(
        symbol=symbol,
        last_price=float(df["close"].iloc[-1]),
        dollar_volume=avg_dollar_volume(df, lookback),
        atr_pct=pct,
        change_pct=change_pct(df, lookback),
        bars=len(df),
    )
