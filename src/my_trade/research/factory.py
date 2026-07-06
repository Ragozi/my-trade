"""Factory helpers to wire multi-provider research from application settings."""

from __future__ import annotations

from my_trade.config import Settings
from my_trade.research.advisor import ResearchAdvisor, ResearchConfig
from my_trade.research.client import ClaudeResearchClient
from my_trade.research.composite import CompositeResearchAdvisor
from my_trade.research.evaluation import ResearchEvaluationStore
from my_trade.research.memory import ResearchMemoryStore
from my_trade.research.postmortem import PostMortemBudget, PostMortemGenerator
from my_trade.research.providers import OpenAIResearchClient, XAIResearchClient
from my_trade.research.rate_limit import ResearchRateLimiter


def _shared_research_config(settings: Settings) -> ResearchConfig:
    rc = settings.research
    return ResearchConfig(
        enabled=True,
        model=rc.model,
        min_confidence=rc.min_confidence,
        max_ideas_per_cycle=rc.max_ideas_per_cycle,
        require_approval_for_entry=rc.require_approval_for_entry,
        block_avoid_for_entry=rc.block_avoid_for_entry,
        block_hold_for_entry=rc.block_hold_for_entry,
        equities_only=rc.equities_only,
        market_hours_only=rc.market_hours_only,
        billing_cooldown_seconds=rc.billing_cooldown_seconds,
    )


def build_claude_client(settings: Settings) -> ClaudeResearchClient | None:
    rc = settings.research
    if not rc.claude_enabled:
        return None
    return ClaudeResearchClient(
        api_key=rc.api_key,
        model=rc.model,
        max_tokens=rc.max_tokens,
        timeout_seconds=rc.timeout_seconds,
    )


def build_workhorse_client(settings: Settings) -> OpenAIResearchClient | XAIResearchClient | None:
    return _build_provider_client(settings, tier="workhorse")


def build_premium_client(settings: Settings) -> OpenAIResearchClient | XAIResearchClient | None:
    rc = settings.research
    if not rc.premium_active:
        return None
    return _build_provider_client(settings, tier="premium")


def _build_provider_client(
    settings: Settings,
    *,
    tier: str,
) -> OpenAIResearchClient | XAIResearchClient | None:
    rc = settings.research
    wh = rc.workhorse
    if tier == "workhorse":
        if not wh.is_active:
            return None
        provider = wh.provider
        openai_model = wh.openai_model
        xai_model = wh.xai_model
        max_tokens = wh.max_tokens
        timeout = wh.timeout_seconds
    else:
        prem = rc.premium
        if not prem.is_active:
            return None
        provider = prem.provider
        openai_model = prem.openai_model
        xai_model = prem.xai_model
        max_tokens = prem.max_tokens
        timeout = prem.timeout_seconds

    if provider == "openai":
        return OpenAIResearchClient(
            api_key=wh.openai_api_key,
            model=openai_model,
            max_tokens=max_tokens,
            timeout_seconds=timeout,
        )
    if provider == "xai":
        return XAIResearchClient(
            api_key=wh.xai_api_key,
            model=xai_model,
            max_tokens=max_tokens,
            timeout_seconds=timeout,
        )
    return None


def build_research_client(settings: Settings) -> ClaudeResearchClient | None:
    """Backward-compatible alias — returns Claude client when premium tier is on."""
    return build_claude_client(settings)


def build_research_memory(
    settings: Settings,
    *,
    client: ClaudeResearchClient | OpenAIResearchClient | XAIResearchClient | None = None,
) -> ResearchMemoryStore | None:
    if not settings.research.enabled:
        return None
    rc = settings.research
    postmortem: PostMortemGenerator | None = None
    pm_client = client or build_postmortem_client(settings)
    if rc.postmortem_enabled and pm_client is not None:
        postmortem = PostMortemGenerator(
            client=pm_client,
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


def _build_tier_advisor(
    settings: Settings,
    *,
    name: str,
    client: object,
    min_interval: int,
    max_calls: int,
) -> ResearchAdvisor:
    limiter = ResearchRateLimiter(
        min_interval_seconds=min_interval,
        max_calls_per_day=max_calls,
    )
    return ResearchAdvisor(
        client,  # type: ignore[arg-type]
        _shared_research_config(settings),
        rate_limiter=limiter,
    )


def build_research_advisor(
    settings: Settings,
    *,
    client: ClaudeResearchClient | None = None,
) -> CompositeResearchAdvisor | ResearchAdvisor | None:
    """Return composite or single-tier advisor when research is enabled."""
    rc = settings.research
    if not rc.enabled or not rc.any_tier_enabled:
        return None

    tiers: list[tuple[str, ResearchAdvisor]] = []

    claude_client = client or build_claude_client(settings)
    if rc.claude_enabled and claude_client is not None and rc.tier_mode != "workhorse_only":
        tiers.append(
            (
                "claude",
                _build_tier_advisor(
                    settings,
                    name="claude",
                    client=claude_client,
                    min_interval=rc.min_interval_seconds,
                    max_calls=rc.max_calls_per_day,
                ),
            )
        )

    prem_client = build_premium_client(settings)
    if prem_client is not None and rc.tier_mode != "workhorse_only":
        prem = rc.premium
        tiers.append(
            (
                "premium",
                _build_tier_advisor(
                    settings,
                    name="premium",
                    client=prem_client,
                    min_interval=prem.min_interval_seconds,
                    max_calls=prem.max_calls_per_day,
                ),
            )
        )

    wh_client = build_workhorse_client(settings)
    if wh_client is not None and rc.tier_mode != "claude_only":
        wh = rc.workhorse
        tiers.append(
            (
                wh.provider,
                _build_tier_advisor(
                    settings,
                    name=wh.provider,
                    client=wh_client,
                    min_interval=wh.min_interval_seconds,
                    max_calls=wh.max_calls_per_day,
                ),
            )
        )

    if not tiers:
        return None
    if len(tiers) == 1:
        return tiers[0][1]

    return CompositeResearchAdvisor(
        config=_shared_research_config(settings),
        tiers=tuple(tiers),
        tier_mode=rc.tier_mode,
    )


def build_postmortem_client(
    settings: Settings,
) -> ClaudeResearchClient | OpenAIResearchClient | XAIResearchClient | None:
    """Prefer Claude, then premium (Grok/GPT-4o), then workhorse mini."""
    rc = settings.research
    if rc.claude_enabled:
        return build_claude_client(settings)
    prem = build_premium_client(settings)
    if prem is not None:
        return prem
    return build_workhorse_client(settings)


def research_is_active(settings: Settings) -> bool:
    """True when any research tier will run for the current asset class."""
    rc = settings.research
    if not rc.enabled or not rc.selected_tier_enabled:
        return False
    if rc.equities_only and not settings.is_equities:
        return False
    return True
