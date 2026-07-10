"""Deterministic screening / universe-selection layer.

Answers "which symbols should we even consider trading?" with a transparent,
testable policy (liquidity + volatility + price gates, then a weighted rank).
It is asset-agnostic: the same logic runs over crypto pairs or equities; only
the ``UniverseSource`` and the ``MarketDataProvider`` differ.

Safety: this layer NEVER touches risk or execution. It only narrows the symbol
set the orchestrator scans; every selected symbol still passes the full
strategy + risk gate before any order. A future Claude layer may *propose* a
universe, but its output must flow through this deterministic screener.
"""

from .filters import passes, rank, select_watchlist
from .metrics import (
    atr_pct,
    average_true_range,
    avg_dollar_volume,
    build_candidate,
    change_pct,
    gap_pct,
    prior_session_close,
)
from .models import Candidate, ScreenerCriteria
from .screener import Screener
from .universe import (
    DEFAULT_CRYPTO_UNIVERSE,
    StaticUniverseSource,
    UniverseSource,
)

__all__ = [
    "DEFAULT_CRYPTO_UNIVERSE",
    "Candidate",
    "Screener",
    "ScreenerCriteria",
    "StaticUniverseSource",
    "UniverseSource",
    "atr_pct",
    "average_true_range",
    "avg_dollar_volume",
    "build_candidate",
    "change_pct",
    "gap_pct",
    "passes",
    "prior_session_close",
    "rank",
    "select_watchlist",
]
