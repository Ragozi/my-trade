"""Lightweight sector / concentration analysis for portfolio-aware prompts."""

from __future__ import annotations

from collections.abc import Sequence

from my_trade.research.models import OpenPositionSummary, PortfolioSnapshot, SectorExposure

# Static sector map — extend as needed; unknown tickers land in "Other".
SYMBOL_SECTOR: dict[str, str] = {
    "AAPL": "Technology",
    "MSFT": "Technology",
    "NVDA": "Technology",
    "AMD": "Technology",
    "GOOGL": "Technology",
    "GOOG": "Technology",
    "META": "Technology",
    "AMZN": "Consumer Discretionary",
    "TSLA": "Consumer Discretionary",
    "JPM": "Financials",
    "BAC": "Financials",
    "GS": "Financials",
    "XOM": "Energy",
    "CVX": "Energy",
    "JNJ": "Healthcare",
    "UNH": "Healthcare",
    "PFE": "Healthcare",
    "LLY": "Healthcare",
    "WMT": "Consumer Staples",
    "KO": "Consumer Staples",
    "DIS": "Communication Services",
    "NFLX": "Communication Services",
    "COIN": "Financials",
    "PLTR": "Technology",
    "INTC": "Technology",
    "AVGO": "Technology",
    "CRM": "Technology",
    "ORCL": "Technology",
    "IBM": "Technology",
    "V": "Financials",
    "MA": "Financials",
}

CONCENTRATION_WARN_PCT = 0.40  # warn when one sector > 40% of equity exposure


def sector_for(symbol: str) -> str:
    return SYMBOL_SECTOR.get(symbol.upper().strip(), "Other")


def build_portfolio_snapshot(
    positions: Sequence[OpenPositionSummary],
    *,
    equity: float,
    candidate_symbols: Sequence[str] = (),
) -> PortfolioSnapshot:
    """Compute sector weights from open positions and emit concentration warnings."""
    if equity <= 0:
        equity = 1.0

    by_sector: dict[str, list[str]] = {}
    sector_value: dict[str, float] = {}
    for pos in positions:
        sec = sector_for(pos.symbol)
        by_sector.setdefault(sec, []).append(pos.symbol.upper())
        sector_value[sec] = sector_value.get(sec, 0.0) + max(pos.market_value, 0.0)

    exposures: list[SectorExposure] = []
    for sec, syms in sorted(by_sector.items()):
        weight = sector_value.get(sec, 0.0) / equity
        exposures.append(
            SectorExposure(
                sector=sec,
                weight_pct=round(weight, 4),
                symbols=tuple(sorted(set(syms))),
            )
        )

    warnings: list[str] = []
    largest_sector = ""
    largest_weight = 0.0
    for exp in exposures:
        if exp.weight_pct > largest_weight:
            largest_weight = exp.weight_pct
            largest_sector = exp.sector
        if exp.weight_pct >= CONCENTRATION_WARN_PCT:
            warnings.append(
                f"High {exp.sector} exposure ({exp.weight_pct:.0%}): "
                f"{', '.join(exp.symbols)}"
            )

    # Candidate symbols that would add to an already-heavy sector.
    held_sectors = {sector_for(p.symbol) for p in positions}
    for sym in candidate_symbols:
        sec = sector_for(sym)
        if sec in held_sectors and sec != "Other":
            held_in_sector = [p.symbol for p in positions if sector_for(p.symbol) == sec]
            if held_in_sector:
                warnings.append(
                    f"Already long {sec} ({', '.join(held_in_sector)}); "
                    f"candidate {sym.upper()} adds correlation risk"
                )

    return PortfolioSnapshot(
        sector_exposures=tuple(exposures),
        concentration_warnings=tuple(dict.fromkeys(warnings)),
        largest_sector=largest_sector,
        largest_sector_weight_pct=largest_weight,
    )
