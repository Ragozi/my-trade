"""Factory helpers to wire Claude research from application settings."""

from __future__ import annotations

from my_trade.config import Settings
from my_trade.research.advisor import ResearchAdvisor, ResearchConfig
from my_trade.research.client import ClaudeResearchClient
from my_trade.research.evaluation import ResearchEvaluationStore
from my_trade.research.memory import ResearchMemoryStore
from my_trade.research.postmortem import PostMortemBudget, PostMortemGenerator
from my_trade.research.rate_limit import ResearchRateLimiter


def build_research_client(settings: Settings) -> ClaudeResearchClient | None:
    rc = settings.research
    if not rc.enabled:
        return None
    return ClaudeResearchClient(
        api_key=rc.api_key,
        model=rc.model,
        max_tokens=rc.max_tokens,
        timeout_seconds=rc.timeout_seconds,
    )


def build_research_memory(
    settings: Settings,
    *,
    client: ClaudeResearchClient | None = None,
) -> ResearchMemoryStore | None:
    if not settings.research.enabled:
        return None
    rc = settings.research
    postmortem: PostMortemGenerator | None = None
    if rc.postmortem_enabled and client is not None:
        postmortem = PostMortemGenerator(
            client=client,
            enabled=True,
            budget=PostMortemBudget(max_per_day=rc.postmortem_max_per_day),
        )
    return ResearchMemoryStore(
        rc.memory_file,
        max_reflections=rc.memory_max_reflections,
        performance_window=rc.performance_window,
        postmortem=postmortem,
    )


def build_research_evaluation(settings: Settings) -> ResearchEvaluationStore | None:
    if not settings.research.enabled:
        return None
    rc = settings.research
    return ResearchEvaluationStore(
        rc.evaluation_file,
        max_records=rc.evaluation_max_records,
    )


def build_research_advisor(
    settings: Settings,
    *,
    client: ClaudeResearchClient | None = None,
) -> ResearchAdvisor | None:
    """Return an advisor when ENABLE_CLAUDE=true, else None."""
    rc = settings.research
    if not rc.enabled:
        return None
    if client is None:
        client = build_research_client(settings)
    if client is None:
        return None
    limiter = ResearchRateLimiter(
        min_interval_seconds=rc.min_interval_seconds,
        max_calls_per_day=rc.max_calls_per_day,
    )
    config = ResearchConfig(
        enabled=True,
        model=rc.model,
        min_confidence=rc.min_confidence,
        max_ideas_per_cycle=rc.max_ideas_per_cycle,
        require_approval_for_entry=rc.require_approval_for_entry,
        equities_only=rc.equities_only,
        market_hours_only=rc.market_hours_only,
        billing_cooldown_seconds=rc.billing_cooldown_seconds,
    )
    return ResearchAdvisor(client, config, rate_limiter=limiter)


def research_is_active(settings: Settings) -> bool:
    """True when Claude research will run for the current asset class."""
    rc = settings.research
    if not rc.enabled:
        return False
    if rc.equities_only and not settings.is_equities:
        return False
    return True
