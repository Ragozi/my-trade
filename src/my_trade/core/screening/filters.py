"""Pure filtering and ranking of screening candidates.

No pandas, no I/O: these functions take ``Candidate`` objects + ``ScreenerCriteria``
and return decisions, so the selection policy is fully deterministic and testable.

Policy:
  1. ``passes`` — a hard gate on price / liquidity / volatility / data sufficiency.
  2. ``rank`` — order survivors by a transparent weighted blend of volatility
     (``atr_pct``, already a fraction) and set-normalized liquidity, then cap at
     ``top_n``. Ties break on symbol for stable, reproducible output.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace

from .models import Candidate, ScreenerCriteria


def passes(candidate: Candidate, criteria: ScreenerCriteria) -> bool:
    """True when a candidate clears every hard gate in ``criteria``."""
    if candidate.bars < criteria.min_bars:
        return False
    if not criteria.min_price <= candidate.last_price <= criteria.max_price:
        return False
    if candidate.dollar_volume < criteria.min_dollar_volume:
        return False
    return criteria.min_atr_pct <= candidate.atr_pct <= criteria.max_atr_pct


def _normalize(values: list[float]) -> list[float]:
    """Min-max normalize to [0, 1]; all-equal inputs map to 0.0 (no signal)."""
    lo = min(values)
    hi = max(values)
    spread = hi - lo
    if spread <= 0:
        return [0.0 for _ in values]
    return [(v - lo) / spread for v in values]


def rank(candidates: Iterable[Candidate], criteria: ScreenerCriteria) -> list[Candidate]:
    """Filter, score, and order candidates best-first (capped at ``top_n``).

    The composite score is ``w_vol * atr_pct + w_liq * normalized_dollar_volume``.
    Liquidity is normalized across the surviving set so the two terms are
    comparable; the returned candidates carry their assigned ``score``.
    """
    survivors = [c for c in candidates if passes(c, criteria)]
    if not survivors:
        return []

    liquidity = _normalize([c.dollar_volume for c in survivors])
    scored = [
        replace(
            c,
            score=criteria.weight_volatility * c.atr_pct
            + criteria.weight_liquidity * liq,
        )
        for c, liq in zip(survivors, liquidity, strict=True)
    ]
    scored.sort(key=lambda c: (-c.score, c.symbol))
    return scored[: criteria.top_n]


def select_watchlist(
    candidates: Iterable[Candidate], criteria: ScreenerCriteria
) -> tuple[str, ...]:
    """Convenience: the ranked symbols only, ready to feed the orchestrator."""
    return tuple(c.symbol for c in rank(candidates, criteria))
