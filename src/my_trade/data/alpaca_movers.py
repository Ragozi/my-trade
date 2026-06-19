"""Dynamic equities universe from Alpaca's screener (most-actives / movers).

Two pieces, cleanly separated for testability:
  * Pure parse helpers (``most_actives_symbols`` / ``movers_symbols``) that turn a
    duck-typed screener response into an ordered, de-duplicated symbol list — no
    network, fully unit-tested.
  * ``AlpacaMoversUniverse`` — the thin I/O boundary that calls Alpaca's
    ``ScreenerClient`` and is fail-safe (returns an empty list on any error).

It satisfies the screening ``UniverseSource`` protocol structurally (``symbols``),
so the deterministic ``Screener`` applies the real price/liquidity/volatility
gates on top — this source only proposes a *candidate* set.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from typing import Any

_log = logging.getLogger("my_trade.data.alpaca_movers")


def _excluded(symbol: str, exclude: frozenset[str]) -> bool:
    return symbol.upper() in exclude


def _dedup_cap(symbols: Iterable[str], top: int) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for sym in symbols:
        key = sym.upper()
        if key and key not in seen:
            seen.add(key)
            out.append(sym)
        if len(out) >= top:
            break
    return out


def most_actives_symbols(
    items: Iterable[Any],
    *,
    top: int,
    min_volume: float = 0.0,
    exclude: Sequence[str] = (),
) -> list[str]:
    """Symbols from a most-actives response (each item has ``symbol``/``volume``)."""
    blocked = frozenset(s.upper() for s in exclude)
    picked: list[str] = []
    for item in items:
        symbol = str(getattr(item, "symbol", "")).strip()
        if not symbol or _excluded(symbol, blocked):
            continue
        volume = float(getattr(item, "volume", 0.0) or 0.0)
        if volume < min_volume:
            continue
        picked.append(symbol)
    return _dedup_cap(picked, top)


def movers_symbols(
    gainers: Iterable[Any],
    losers: Iterable[Any],
    *,
    direction: str,
    top: int,
    exclude: Sequence[str] = (),
) -> list[str]:
    """Symbols from a market-movers response.

    ``direction`` is one of ``gainers``, ``losers``, or ``both`` (gainers first).
    """
    blocked = frozenset(s.upper() for s in exclude)
    chosen: list[Any]
    if direction == "gainers":
        chosen = list(gainers)
    elif direction == "losers":
        chosen = list(losers)
    else:  # both
        chosen = [*gainers, *losers]
    symbols = [
        str(getattr(m, "symbol", "")).strip()
        for m in chosen
        if str(getattr(m, "symbol", "")).strip()
        and not _excluded(str(getattr(m, "symbol", "")), blocked)
    ]
    return _dedup_cap(symbols, top)


class AlpacaMoversUniverse:
    """Fail-safe equities ``UniverseSource`` backed by Alpaca's ScreenerClient."""

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        *,
        source: str = "actives",
        top: int = 20,
        min_volume: float = 0.0,
        exclude: Sequence[str] = (),
    ) -> None:
        from alpaca.data.historical.screener import ScreenerClient

        self._client: Any = ScreenerClient(api_key=api_key, secret_key=api_secret)
        self._source = source
        self._top = top
        self._min_volume = min_volume
        self._exclude = tuple(exclude)

    def symbols(self) -> Sequence[str]:
        try:
            if self._source in {"gainers", "losers", "both"}:
                return self._fetch_movers()
            return self._fetch_actives()
        except Exception as exc:  # boundary: degrade to "no candidates", never crash
            _log.warning("movers universe fetch failed: %s", exc)
            return ()

    def _fetch_actives(self) -> Sequence[str]:
        from alpaca.data.requests import MostActivesRequest

        resp = self._client.get_most_actives(MostActivesRequest(top=self._top))
        items = getattr(resp, "most_actives", []) or []
        return most_actives_symbols(
            items, top=self._top, min_volume=self._min_volume, exclude=self._exclude
        )

    def _fetch_movers(self) -> Sequence[str]:
        from alpaca.data.requests import MarketMoversRequest

        resp = self._client.get_market_movers(MarketMoversRequest(top=self._top))
        return movers_symbols(
            getattr(resp, "gainers", []) or [],
            getattr(resp, "losers", []) or [],
            direction=self._source,
            top=self._top,
            exclude=self._exclude,
        )
