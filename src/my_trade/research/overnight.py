"""Overnight / premarket gap study for research context (pure + thin I/O)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Protocol

from my_trade.core.screening.metrics import gap_pct, prior_session_close


class BarLoader(Protocol):
    def __call__(self, symbol: str, timeframe: str, limit: int | None = None) -> object: ...


def overnight_snapshot(
    *,
    symbol: str,
    last_price: float,
    prior_close: float | None,
    change_pct: float = 0.0,
    dollar_volume: float = 0.0,
    news_headlines: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Build one symbol's overnight/premarket study row for the research prompt."""
    gap = gap_pct(last_price, prior_close)
    return {
        "symbol": symbol.upper(),
        "last_price": round(last_price, 4),
        "prior_close": round(prior_close, 4) if prior_close else None,
        "gap_pct": round(gap, 4),
        "gap_label": (
            "gap_up"
            if gap >= 0.03
            else "gap_down"
            if gap <= -0.03
            else "flat_overnight"
        ),
        "intraday_change_pct": round(change_pct, 4),
        "dollar_volume": round(dollar_volume, 2),
        "news_headlines": list(news_headlines[:3]),
    }


def gather_overnight_moves(
    *,
    symbols: tuple[str, ...],
    get_bars: BarLoader,
    as_of: datetime,
    ranked_meta: dict[str, dict[str, float]] | None = None,
) -> tuple[dict[str, Any], ...]:
    """Compute overnight gap vs prior daily close for each candidate.

    ``ranked_meta`` may supply last_price / change_pct / dollar_volume from the
    screener so we avoid a second intraday fetch when available.
    """
    day: date = as_of.date()
    meta = ranked_meta or {}
    out: list[dict[str, Any]] = []
    for symbol in symbols:
        key = symbol.upper()
        info = meta.get(key, {})
        last_price = float(info.get("last_price") or 0.0)
        change = float(info.get("change_pct") or 0.0)
        dv = float(info.get("dollar_volume") or 0.0)
        prior = float(info["prior_close"]) if info.get("prior_close") else None
        if prior is None or last_price <= 0:
            try:
                daily = get_bars(symbol, "1Day", 10)
                prior = prior_session_close(daily, as_of=day)  # type: ignore[arg-type]
            except Exception:
                prior = None
            if last_price <= 0:
                try:
                    bars = get_bars(symbol, "5Min", 5)
                    if bars is not None and hasattr(bars, "empty") and not bars.empty:
                        last_price = float(bars["close"].iloc[-1])  # type: ignore[index]
                except Exception:
                    last_price = 0.0
        if last_price <= 0 and prior is None:
            continue
        out.append(
            overnight_snapshot(
                symbol=key,
                last_price=last_price,
                prior_close=prior,
                change_pct=change,
                dollar_volume=dv,
            )
        )
    out.sort(key=lambda row: abs(float(row.get("gap_pct") or 0.0)), reverse=True)
    return tuple(out)
