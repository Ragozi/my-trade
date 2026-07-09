"""ResearchAdvisor — optional Claude hook for the trading loop."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from my_trade.research.client import ResearchClient
from my_trade.research.models import ClaudeProposal, ResearchResult, TradeAction, TradeIdea
from my_trade.research.rate_limit import ResearchRateLimiter

_log = logging.getLogger("my_trade.research.advisor")


@dataclass(frozen=True)
class ResearchConfig:
    enabled: bool = False
    model: str = "claude-sonnet-4-6"
    min_confidence: float = 0.55
    entry_veto_min_confidence: float = 0.10
    max_ideas_per_cycle: int = 5
    require_approval_for_entry: bool = False
    block_avoid_for_entry: bool = True
    block_hold_for_entry: bool = True
    equities_only: bool = True
    market_hours_only: bool = True
    billing_cooldown_seconds: int = 3600


class ResearchAdvisor:
    """Advisory research facade — never submits orders."""

    def __init__(
        self,
        client: ResearchClient,
        config: ResearchConfig,
        *,
        rate_limiter: ResearchRateLimiter | None = None,
    ) -> None:
        self._client = client
        self._config = config
        self._limiter = rate_limiter or ResearchRateLimiter()

    @property
    def config(self) -> ResearchConfig:
        return self._config

    def is_active_for(self, asset_class: str) -> bool:
        if not self._config.enabled:
            return False
        if self._config.equities_only and asset_class != "equities":
            return False
        return True

    def propose(
        self,
        context: object,
        *,
        when: datetime,
    ) -> ResearchResult:
        """Call Claude or return a skipped proposal when rate-limited."""
        if not self._config.enabled:
            return ResearchResult(
                proposal=ClaudeProposal(skipped=True, skip_reason="disabled"),
                called_api=False,
            )

        reason = self._limiter.skip_reason(when)
        if reason:
            _log.info("research skipped: %s", reason)
            return ResearchResult(
                proposal=ClaudeProposal(skipped=True, skip_reason=reason),
                called_api=False,
                rate_limited=True,
            )

        try:
            proposal = self._client.propose_equity_ideas(
                context,
                max_ideas=self._config.max_ideas_per_cycle,
            )
            self._limiter.record_call(when)
            _log.info(
                "research returned %d ideas (%d long)",
                len(proposal.ideas),
                len(proposal.long_ideas),
            )
            return ResearchResult(proposal=proposal, called_api=True)
        except Exception as exc:
            msg = str(exc)
            if "credit balance" in msg.lower() or "billing" in msg.lower() or "insufficient_quota" in msg.lower():
                self._limiter.record_billing_failure(
                    when, cooldown_seconds=self._config.billing_cooldown_seconds
                )
                _log.error(
                    "research call failed: Anthropic account needs credits — "
                    "add billing at https://console.anthropic.com/settings/billing "
                    "(pausing Claude calls for 1h)"
                )
            else:
                _log.warning("research call failed: %s", exc)
            return ResearchResult(
                proposal=ClaudeProposal(skipped=True, skip_reason=msg),
                called_api=False,
            )

    def approved_symbols(self, proposal: ClaudeProposal) -> frozenset[str]:
        """Symbols Claude marked as long above the confidence threshold."""
        return frozenset(
            idea.symbol
            for idea in proposal.ideas
            if idea.action is TradeAction.LONG and idea.confidence >= self._config.min_confidence
        )

    def allows_entry(
        self,
        symbol: str,
        proposal: ClaudeProposal,
        *,
        sticky_idea: TradeIdea | None = None,
    ) -> bool:
        """Whether deterministic entry may proceed for this symbol."""
        from my_trade.research.gating import allows_entry_with_gates

        return allows_entry_with_gates(
            proposal,
            symbol,
            min_confidence=self._config.min_confidence,
            block_avoid=self._config.block_avoid_for_entry,
            block_hold=self._config.block_hold_for_entry,
            require_long_approval=self._config.require_approval_for_entry,
            sticky_idea=sticky_idea,
            entry_veto_min_confidence=self._config.entry_veto_min_confidence,
        )

    def entry_veto_reason(
        self,
        symbol: str,
        proposal: ClaudeProposal,
        *,
        sticky_idea: TradeIdea | None = None,
    ) -> str | None:
        from my_trade.research.gating import research_veto_reason

        return research_veto_reason(
            proposal,
            symbol,
            min_confidence=self._config.min_confidence,
            block_avoid=self._config.block_avoid_for_entry,
            block_hold=self._config.block_hold_for_entry,
            require_long_approval=self._config.require_approval_for_entry,
            sticky_idea=sticky_idea,
            entry_veto_min_confidence=self._config.entry_veto_min_confidence,
        )
