"""Pure helpers for normalizing and validating OHLCV bar data.

No network and no Alpaca SDK here — these functions take raw records or
DataFrames and return clean, time-indexed DataFrames, so they are trivially
unit-testable. The live Alpaca client (see ``provider.py``) is responsible for
fetching; it delegates all cleaning to these helpers.

Bar schema: a time-indexed DataFrame with float columns
``open, high, low, close, volume`` (index is the bar timestamp, ascending).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime

import pandas as pd

OHLC_COLUMNS = ("open", "high", "low", "close")
OHLCV_COLUMNS = (*OHLC_COLUMNS, "volume")

_TIMEFRAME_SECONDS: dict[str, int] = {
    "1Min": 60,
    "2Min": 120,
    "5Min": 300,
    "15Min": 900,
    "30Min": 1800,
    "1Hour": 3600,
    "1Day": 86_400,
}


def normalize_symbol(symbol: str) -> str:
    """Canonicalize a symbol for comparison (Alpaca returns ``BTCUSD``,
    config uses ``BTC/USD``)."""
    return symbol.replace("/", "").upper()


def symbols_match(a: str, b: str) -> bool:
    return normalize_symbol(a) == normalize_symbol(b)


def timeframe_to_seconds(timeframe: str) -> int:
    """Map an Alpaca-style timeframe string to seconds.

    Raises:
        ValueError: for an unknown timeframe.
    """
    try:
        return _TIMEFRAME_SECONDS[timeframe]
    except KeyError as exc:
        raise ValueError(f"unknown timeframe {timeframe!r}") from exc


def empty_frame() -> pd.DataFrame:
    """An empty, correctly-typed OHLCV frame."""
    frame: pd.DataFrame = pd.DataFrame(columns=list(OHLCV_COLUMNS))
    return frame


def bars_to_frame(records: Iterable[Mapping[str, object]]) -> pd.DataFrame:
    """Build a clean, time-indexed OHLCV frame from raw bar records.

    Each record must contain ``timestamp`` plus the OHLCV fields. Returns an
    empty frame (with the right columns) when there are no records.
    """
    rows = list(records)
    if not rows:
        return empty_frame()

    frame: pd.DataFrame = pd.DataFrame(rows)
    for col in OHLCV_COLUMNS:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    indexed: pd.DataFrame = frame.set_index("timestamp").sort_index()
    return indexed


def clean_bars(df: pd.DataFrame) -> pd.DataFrame:
    """Drop rows with missing OHLC, de-duplicate timestamps, sort ascending."""
    if df.empty:
        return df
    cleaned: pd.DataFrame = df.dropna(subset=list(OHLC_COLUMNS))
    cleaned = cleaned[~cleaned.index.duplicated(keep="last")]
    cleaned = cleaned.sort_index()
    return cleaned


def forward_fill_zero_volume(df: pd.DataFrame) -> pd.DataFrame:
    """Replace non-positive / NaN volume with the previous bar's volume.

    Alpaca crypto bars frequently report ``volume == 0`` for the current,
    not-yet-closed candle; treating that as real volume breaks volume filters.
    Leading bars with no prior volume are set to 0.
    """
    if df.empty or "volume" not in df.columns:
        return df
    out: pd.DataFrame = df.copy()
    vol = out["volume"].where(out["volume"] > 0)
    out["volume"] = vol.ffill().fillna(0.0)
    return out


def has_min_bars(df: pd.DataFrame, minimum: int) -> bool:
    """True when the frame has at least ``minimum`` rows."""
    return not df.empty and len(df) >= minimum


def is_stale(
    df: pd.DataFrame,
    now: datetime,
    timeframe_seconds: int,
    max_lag_bars: int = 2,
) -> bool:
    """True when the most recent bar is older than ``max_lag_bars`` timeframes.

    An empty frame is considered stale (no data ⇒ do not trade).
    """
    if df.empty:
        return True
    last_ts: datetime = pd.Timestamp(df.index[-1]).to_pydatetime()
    lag_seconds = (now - last_ts).total_seconds()
    return lag_seconds > timeframe_seconds * max_lag_bars
