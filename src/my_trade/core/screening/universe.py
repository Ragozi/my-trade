"""The candidate-universe boundary: *what symbols to even consider*.

The screener depends on this ``Protocol`` rather than on any specific source, so
the same deterministic filtering/ranking works over:
  * a static curated list (``StaticUniverseSource`` — used first, for crypto),
  * Alpaca "most-actives"/movers (an equities I/O source added in the next
    increment), or
  * a Claude-proposed watchlist later (advisory only; still filtered by the
    deterministic screener before anything is traded).

Implementations MUST be fail-safe: return an empty sequence rather than raising,
so a universe outage degrades to "no new candidates", never a crash.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

# A small, liquid default crypto universe for Alpaca. Used to exercise the
# screener end-to-end before the equities data path lands.
DEFAULT_CRYPTO_UNIVERSE: tuple[str, ...] = (
    "BTC/USD",
    "ETH/USD",
    "SOL/USD",
    "LTC/USD",
    "BCH/USD",
    "AVAX/USD",
    "LINK/USD",
    "DOGE/USD",
)


@runtime_checkable
class UniverseSource(Protocol):
    """Provides the raw candidate symbols for a screening pass."""

    def symbols(self) -> Sequence[str]:
        """Return candidate symbols (empty sequence if unavailable)."""
        ...


class StaticUniverseSource:
    """A fixed, configured universe. Order-preserving and de-duplicated."""

    def __init__(self, symbols: Sequence[str]) -> None:
        seen: set[str] = set()
        unique: list[str] = []
        for sym in symbols:
            key = sym.strip().upper()
            if key and key not in seen:
                seen.add(key)
                unique.append(sym.strip())
        self._symbols: tuple[str, ...] = tuple(unique)

    def symbols(self) -> Sequence[str]:
        return self._symbols


class MergedUniverseSource:
    """Union of multiple universe sources with de-duplication and exclusions."""

    def __init__(
        self,
        *sources: UniverseSource,
        exclude: frozenset[str] = frozenset(),
    ) -> None:
        self._sources = sources
        self._exclude = exclude

    def symbols(self) -> Sequence[str]:
        seen: set[str] = set()
        out: list[str] = []
        for source in self._sources:
            try:
                batch = source.symbols()
            except Exception:
                continue
            for sym in batch:
                key = sym.strip().upper()
                if not key or key in seen or key in self._exclude:
                    continue
                seen.add(key)
                out.append(sym.strip())
        return tuple(out)
