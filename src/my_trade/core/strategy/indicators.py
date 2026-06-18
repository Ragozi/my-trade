"""Indicator computation (pandas) and the pandas->scalar bridge.

This is the only strategy module that touches pandas / pandas_ta. It computes
indicator columns and extracts a pure ``BarSnapshot`` for the decision logic in
``signals.py``. It makes no trading decisions itself.
"""

from __future__ import annotations

import pandas as pd
import pandas_ta as ta

from .models import BarSnapshot, StrategyParams


def rolling_vwap(df: pd.DataFrame) -> pd.Series:
    """Session-style cumulative VWAP over the provided window."""
    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    cum_vol = df["volume"].cumsum()
    cum_tp_vol = (typical * df["volume"]).cumsum()
    return cum_tp_vol / cum_vol.replace(0, float("nan"))


def add_indicators(df: pd.DataFrame, params: StrategyParams) -> pd.DataFrame:
    """Return a copy of ``df`` with EMA/RSI/VWAP/volume-SMA/MACD/Bollinger columns."""
    if df.empty:
        return df
    out: pd.DataFrame = df.copy()
    out["ema_trend"] = ta.ema(out["close"], length=params.ema_trend)
    out["rsi"] = ta.rsi(out["close"], length=params.rsi_period)
    out["vol_sma"] = ta.sma(out["volume"], length=params.volume_sma_period)
    out["vwap"] = rolling_vwap(out)

    macd = ta.macd(out["close"], fast=params.macd_fast, slow=params.macd_slow,
                   signal=params.macd_signal)
    if macd is not None and not macd.empty:
        hist_cols = [c for c in macd.columns if c.startswith("MACDh")]
        if hist_cols:
            out["macd_hist"] = macd[hist_cols[0]]

    bands = ta.bbands(out["close"], length=params.bollinger_period, std=params.bollinger_std)
    if bands is not None and not bands.empty:
        for prefix, name in (("BBL", "bb_lower"), ("BBM", "bb_mid"), ("BBU", "bb_upper")):
            cols = [c for c in bands.columns if c.startswith(prefix)]
            if cols:
                out[name] = bands[cols[0]]
    return out


def opt_float(value: object) -> float | None:
    """Coerce a cell to float, returning None for missing/NaN."""
    if value is None or pd.isna(value):
        return None
    return float(value)  # type: ignore[arg-type]


def extract_snapshot(df_with_indicators: pd.DataFrame) -> BarSnapshot | None:
    """Pull the last/previous bar's indicators into a pure ``BarSnapshot``.

    Returns ``None`` when there are fewer than two bars (cannot compute prev).
    """
    if df_with_indicators.empty or len(df_with_indicators) < 2:
        return None
    row = df_with_indicators.iloc[-1]
    prev = df_with_indicators.iloc[-2]
    return BarSnapshot(
        close=float(row["close"]),
        vwap=opt_float(row.get("vwap")),
        rsi=opt_float(row.get("rsi")),
        rsi_prev=opt_float(prev.get("rsi")),
        macd_hist=opt_float(row.get("macd_hist")),
        macd_hist_prev=opt_float(prev.get("macd_hist")),
        bb_lower=opt_float(row.get("bb_lower")),
        bb_mid=opt_float(row.get("bb_mid")),
        volume=float(row["volume"]),
        prev_volume=float(prev["volume"]),
        vol_sma=opt_float(row.get("vol_sma")),
    )
