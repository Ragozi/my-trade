"""Structured contracts for the Claude research layer (advisory only)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class InstrumentType(StrEnum):
    SHARES = "shares"
    OPTIONS = "options"
    LEAPS = "leaps"


class TradeAction(StrEnum):
    LONG = "long"
    HOLD = "hold"
    AVOID = "avoid"


class OpenPositionSummary(BaseModel):
    symbol: str
    qty: float
    avg_entry_price: float
    market_value: float
    unrealized_pl: float


class PerformanceSummary(BaseModel):
    """Rolling stats over recent closed trades (for Claude reflection)."""

    sample_size: int = 0
    wins: int = 0
    losses: int = 0
    flats: int = 0
    win_rate: float = 0.0
    avg_pnl_estimate: float = 0.0


class SectorExposure(BaseModel):
    sector: str
    weight_pct: float = 0.0
    symbols: tuple[str, ...] = ()


class PortfolioSnapshot(BaseModel):
    """Sector concentration derived from open positions."""

    sector_exposures: tuple[SectorExposure, ...] = ()
    concentration_warnings: tuple[str, ...] = ()
    largest_sector: str = ""
    largest_sector_weight_pct: float = 0.0


class CycleComparison(BaseModel):
    """One symbol's Claude vs strategy read for a cycle."""

    ts: datetime
    symbol: str
    claude_long: bool = False
    strategy_signal: bool = False
    alignment: Literal["both_agree", "claude_only", "strategy_only", "both_pass"] = "both_pass"


class ComparisonSummary(BaseModel):
    """Aggregate Claude vs deterministic alignment stats."""

    sample_cycles: int = 0
    both_agree: int = 0
    claude_only: int = 0
    strategy_only: int = 0
    both_pass: int = 0
    entries_tracked: int = 0
    closed_trades: int = 0
    avg_pnl_by_source: dict[str, float] = Field(default_factory=dict)


class ClosedTradeReflection(BaseModel):
    """Post-mortem on a closed position — fed back into future research calls."""

    symbol: str
    closed_at: datetime
    outcome: Literal["win", "loss", "flat", "unknown"] = "unknown"
    pnl_estimate: float | None = None
    exit_reason: str = ""
    entry_price: float | None = None
    thesis_at_entry: str = ""
    summary: str = ""
    llm_summary: str = ""

    @field_validator("symbol", mode="before")
    @classmethod
    def _upper_symbol(cls, value: object) -> str:
        return str(value).upper().strip()


class ResearchContext(BaseModel):
    """Snapshot passed to Claude — no secrets, no raw API keys."""

    asset_class: str
    equity: float
    day_pnl: float
    peak_equity: float
    open_positions: tuple[OpenPositionSummary, ...] = ()
    candidate_symbols: tuple[str, ...] = ()
    session_open: bool = True
    as_of: datetime
    open_risk_dollars: float = 0.0
    open_risk_pct: float = 0.0
    recent_reflections: tuple[ClosedTradeReflection, ...] = ()
    performance: PerformanceSummary | None = None
    portfolio: PortfolioSnapshot | None = None
    comparison_summary: ComparisonSummary | None = None
    daily_brief: dict[str, Any] | None = None
    trade_knowledge: tuple[dict[str, Any], ...] = ()
    technical_scans: tuple[dict[str, Any], ...] = ()
    recent_news: tuple[dict[str, Any], ...] = ()
    overnight_moves: tuple[dict[str, Any], ...] = ()

    @field_validator("candidate_symbols", mode="before")
    @classmethod
    def _normalize_symbols(cls, value: object) -> tuple[str, ...]:
        if value is None:
            return ()
        if isinstance(value, str):
            return (value.upper(),)
        return tuple(str(s).upper() for s in value)


class TradeIdea(BaseModel):
    """One advisory trade idea from Claude."""

    symbol: str
    action: TradeAction = TradeAction.HOLD
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    instrument: InstrumentType = InstrumentType.SHARES
    thesis: str = ""
    time_horizon: Literal["intraday", "swing", "position"] = "swing"
    suggested_stop_pct: float | None = Field(default=None, ge=0.0, le=0.5)
    suggested_target_pct: float | None = Field(default=None, ge=0.0, le=1.0)
    catalysts: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()

    @field_validator("symbol", mode="before")
    @classmethod
    def _upper_symbol(cls, value: object) -> str:
        return str(value).upper().strip()


class ClaudeProposal(BaseModel):
    """Validated batch of ideas returned by the research client."""

    ideas: tuple[TradeIdea, ...] = ()
    summary: str = ""
    model: str = ""
    provider: str = ""
    skipped: bool = False
    skip_reason: str = ""
    latency_ms: float | None = None

    @property
    def long_ideas(self) -> tuple[TradeIdea, ...]:
        return tuple(i for i in self.ideas if i.action is TradeAction.LONG)


class ResearchResult(BaseModel):
    """Outcome of one advisor cycle (may be skipped due to rate limits)."""

    proposal: ClaudeProposal
    called_api: bool = False
    rate_limited: bool = False
