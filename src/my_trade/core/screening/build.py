"""Wire universe sources from application settings (shared by bot + API)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from my_trade.core.screening.symbol_filters import merged_exclude_set
from my_trade.core.screening.universe import MergedUniverseSource, StaticUniverseSource, UniverseSource
from my_trade.data.alpaca_movers import AlpacaMoversUniverse

if TYPE_CHECKING:
    from my_trade.config import Settings


def build_equities_universe(settings: Settings) -> tuple[UniverseSource, str]:
    """Return (universe source, human-readable source label) for equities screening."""
    sc = settings.screener
    exclude = merged_exclude_set(
        extra=frozenset(s.upper() for s in sc.exclude_symbols),
        exclude_leveraged_etfs=sc.exclude_leveraged_etfs,
        exclude_large_caps=sc.exclude_large_caps,
    )

    if not sc.use_movers and not sc.movers_only:
        seed = sc.seed_symbols if sc.seed_symbols else settings.symbols
        return StaticUniverseSource(seed), f"seed({len(seed)})"

    movers = AlpacaMoversUniverse(
        settings.alpaca.api_key,
        settings.alpaca.api_secret,
        source=sc.movers_source,
        top=sc.movers_top,
        min_volume=sc.movers_min_volume,
        exclude=tuple(exclude),
    )

    if sc.movers_only or not sc.merge_seed_with_movers:
        label = f"movers({sc.movers_source},top={sc.movers_top})"
        if sc.movers_only:
            label = f"movers-only({sc.movers_source},top={sc.movers_top})"
        return movers, label

    seed = sc.seed_symbols if sc.seed_symbols else settings.symbols
    seed_src = StaticUniverseSource(seed)
    return (
        MergedUniverseSource(seed_src, movers, exclude=exclude),
        f"seed({len(seed)})+movers({sc.movers_source},top={sc.movers_top})",
    )
