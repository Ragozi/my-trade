"""Claude research layer (Phase 4) — ADVISORY ONLY, guardrailed."""

from my_trade.research.advisor import ResearchAdvisor, ResearchConfig
from my_trade.research.client import ClaudeResearchClient, MockClaudeResearchClient
from my_trade.research.context import build_research_context
from my_trade.research.evaluation import ResearchEvaluationStore
from my_trade.research.factory import (
    build_research_advisor,
    build_research_client,
    build_research_evaluation,
    build_research_memory,
    research_is_active,
)
from my_trade.research.history import (
    compute_performance,
    pair_trades_from_events,
    summarize_reflection,
)
from my_trade.research.memory import ResearchMemoryStore
from my_trade.research.models import (
    ClaudeProposal,
    ClosedTradeReflection,
    ComparisonSummary,
    InstrumentType,
    OpenPositionSummary,
    PerformanceSummary,
    PortfolioSnapshot,
    ResearchContext,
    ResearchResult,
    TradeAction,
    TradeIdea,
)
from my_trade.research.portfolio import build_portfolio_snapshot, sector_for
from my_trade.research.postmortem import PostMortemGenerator, MockPostMortemClient
from my_trade.research.rate_limit import ResearchRateLimiter
from my_trade.research.reflection import build_reflection

__all__ = [
    "ClaudeProposal",
    "ClaudeResearchClient",
    "ClosedTradeReflection",
    "ComparisonSummary",
    "InstrumentType",
    "MockClaudeResearchClient",
    "MockPostMortemClient",
    "OpenPositionSummary",
    "PerformanceSummary",
    "PortfolioSnapshot",
    "PostMortemGenerator",
    "ResearchAdvisor",
    "ResearchConfig",
    "ResearchContext",
    "ResearchEvaluationStore",
    "ResearchMemoryStore",
    "ResearchRateLimiter",
    "ResearchResult",
    "TradeAction",
    "TradeIdea",
    "build_portfolio_snapshot",
    "build_research_advisor",
    "build_research_client",
    "build_research_context",
    "build_research_evaluation",
    "build_research_memory",
    "build_reflection",
    "compute_performance",
    "pair_trades_from_events",
    "research_is_active",
    "sector_for",
    "summarize_reflection",
]
