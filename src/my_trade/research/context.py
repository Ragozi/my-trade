"""Build research context from live monitoring state (pure assembly)."""

from __future__ import annotations

from datetime import datetime

from my_trade.core.monitoring.account import AccountSnapshot
from typing import Any

from my_trade.research.models import (
    ClosedTradeReflection,
    ComparisonSummary,
    OpenPositionSummary,
    PerformanceSummary,
    PortfolioSnapshot,
    ResearchContext,
)
from my_trade.research.portfolio import build_portfolio_snapshot


def build_research_context(
    *,
    snapshot: AccountSnapshot,
    candidate_symbols: tuple[str, ...],
    asset_class: str,
    session_open: bool,
    as_of: datetime,
    equity: float,
    day_pnl: float,
    peak_equity: float,
    open_risk_dollars: float = 0.0,
    recent_reflections: tuple[ClosedTradeReflection, ...] = (),
    performance: PerformanceSummary | None = None,
    portfolio: PortfolioSnapshot | None = None,
    comparison_summary: ComparisonSummary | None = None,
    daily_brief: dict[str, Any] | None = None,
) -> ResearchContext:
    open_positions = tuple(
        OpenPositionSummary(
            symbol=p.symbol,
            qty=p.qty,
            avg_entry_price=p.avg_entry_price,
            market_value=p.market_value,
            unrealized_pl=p.unrealized_pl,
        )
        for p in snapshot.positions
    )
    if portfolio is None:
        portfolio = build_portfolio_snapshot(
            open_positions, equity=equity, candidate_symbols=candidate_symbols
        )
    open_risk_pct = (open_risk_dollars / equity) if equity > 0 else 0.0
    return ResearchContext(
        asset_class=asset_class,
        equity=equity,
        day_pnl=day_pnl,
        peak_equity=peak_equity,
        open_positions=open_positions,
        candidate_symbols=candidate_symbols,
        session_open=session_open,
        as_of=as_of,
        open_risk_dollars=open_risk_dollars,
        open_risk_pct=open_risk_pct,
        recent_reflections=recent_reflections,
        performance=performance,
        portfolio=portfolio,
        comparison_summary=comparison_summary,
        daily_brief=daily_brief,
    )
