"""Recent headlines for research context (Alpaca News API, fail-safe)."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

_log = logging.getLogger("my_trade.research.news")


def fetch_recent_news(
    symbols: Sequence[str],
    *,
    api_key: str,
    api_secret: str,
    as_of: datetime,
    lookback_hours: int = 72,
    max_per_symbol: int = 3,
) -> tuple[dict[str, Any], ...]:
    """Return recent news snippets for candidate symbols (empty on any failure)."""
    if not symbols or not api_key or not api_secret:
        return ()

    syms = [s.strip().upper() for s in symbols if s.strip()]
    if not syms:
        return ()

    try:
        from alpaca.data.historical.news import NewsClient
        from alpaca.data.requests import NewsRequest
    except ImportError:
        _log.debug("alpaca news client unavailable")
        return ()

    start = as_of.astimezone(UTC) - timedelta(hours=lookback_hours)
    end = as_of.astimezone(UTC)
    client = NewsClient(api_key=api_key, secret_key=api_secret)
    rows: list[dict[str, Any]] = []

    try:
        for sym in syms[:12]:
            try:
                resp = client.get_news(
                    NewsRequest(
                        symbols=sym,
                        start=start,
                        end=end,
                        limit=max_per_symbol,
                        sort="desc",
                    )
                )
            except Exception as exc:
                _log.debug("news fetch failed for %s: %s", sym, exc)
                continue
            for article in getattr(resp, "news", []) or []:
                rows.append(
                    {
                        "symbol": sym,
                        "headline": str(getattr(article, "headline", "") or "")[:240],
                        "summary": str(getattr(article, "summary", "") or "")[:400],
                        "source": str(getattr(article, "source", "") or ""),
                        "created_at": str(getattr(article, "created_at", "") or ""),
                        "url": str(getattr(article, "url", "") or ""),
                    }
                )
    except Exception as exc:
        _log.warning("news fetch failed: %s", exc)
        return ()

    return tuple(rows)
