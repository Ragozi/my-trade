"""Composite advisor — routes calls across premium (Claude) and workhorse tiers."""

from __future__ import annotations

import logging
from datetime import datetime

from my_trade.research.advisor import ResearchAdvisor, ResearchConfig
from my_trade.research.models import ClaudeProposal, ResearchResult, TradeAction

_log = logging.getLogger("my_trade.research.composite")

_VALID_MODES = frozenset({"workhorse_only", "claude_only", "both"})


class CompositeResearchAdvisor:
    """Tries tiers in order; falls through when a tier is rate-limited."""

    def __init__(
        self,
        *,
        config: ResearchConfig,
        tiers: tuple[tuple[str, ResearchAdvisor], ...],
        tier_mode: str = "both",
    ) -> None:
        if tier_mode not in _VALID_MODES:
            raise ValueError(f"RESEARCH_TIER_MODE must be one of {_VALID_MODES}, got {tier_mode!r}")
        self._config = config
        self._tiers = tiers
        self._tier_mode = tier_mode

    @property
    def config(self) -> ResearchConfig:
        return self._config

    def is_active_for(self, asset_class: str) -> bool:
        return self._config.enabled and (
            not self._config.equities_only or asset_class == "equities"
        )

    def _ordered_tiers(self) -> tuple[tuple[str, ResearchAdvisor], ...]:
        if self._tier_mode == "claude_only":
            return tuple(t for t in self._tiers if t[0] == "claude")
        if self._tier_mode == "workhorse_only":
            return tuple(t for t in self._tiers if t[0] not in ("claude", "premium"))
        # both: claude → premium → workhorse (insertion order from factory)
        return self._tiers

    def propose(
        self,
        context: object,
        *,
        when: datetime,
    ) -> ResearchResult:
        if not self._config.enabled:
            return ResearchResult(
                proposal=ClaudeProposal(skipped=True, skip_reason="disabled"),
                called_api=False,
            )

        last: ResearchResult | None = None
        for name, advisor in self._ordered_tiers():
            result = advisor.propose(context, when=when)
            if result.called_api:
                proposal = result.proposal.model_copy(
                    update={"provider": result.proposal.provider or name}
                )
                _log.info("research tier %s returned %d ideas", name, len(proposal.ideas))
                return ResearchResult(
                    proposal=proposal,
                    called_api=True,
                    rate_limited=result.rate_limited,
                )
            last = result
            if not result.proposal.skipped:
                return result

        if last is not None:
            return last
        return ResearchResult(
            proposal=ClaudeProposal(skipped=True, skip_reason="no research tiers configured"),
            called_api=False,
        )

    def approved_symbols(self, proposal: ClaudeProposal) -> frozenset[str]:
        """Symbols marked long above confidence threshold (shared config)."""
        return frozenset(
            idea.symbol
            for idea in proposal.ideas
            if idea.action is TradeAction.LONG
            and idea.confidence >= self._config.min_confidence
        )

    def allows_entry(self, symbol: str, proposal: ClaudeProposal) -> bool:
        from my_trade.research.gating import allows_entry_with_gates

        return allows_entry_with_gates(
            proposal,
            symbol,
            min_confidence=self._config.min_confidence,
            block_avoid=self._config.block_avoid_for_entry,
            block_hold=self._config.block_hold_for_entry,
            require_long_approval=self._config.require_approval_for_entry,
        )

    def entry_veto_reason(self, symbol: str, proposal: ClaudeProposal) -> str | None:
        from my_trade.research.gating import research_veto_reason

        return research_veto_reason(
            proposal,
            symbol,
            min_confidence=self._config.min_confidence,
            block_avoid=self._config.block_avoid_for_entry,
            block_hold=self._config.block_hold_for_entry,
            require_long_approval=self._config.require_approval_for_entry,
        )
