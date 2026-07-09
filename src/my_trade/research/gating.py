"""Research gating — when LLM ideas may block deterministic entries."""

from __future__ import annotations

from my_trade.research.models import ClaudeProposal, TradeAction, TradeIdea


def idea_for_symbol(proposal: ClaudeProposal, symbol: str) -> TradeIdea | None:
    sym = symbol.upper()
    for idea in proposal.ideas:
        if idea.symbol.upper() == sym:
            return idea
    return None


def _effective_idea(
    proposal: ClaudeProposal | None,
    symbol: str,
    *,
    sticky_idea: TradeIdea | None,
    entry_veto_min_confidence: float,
) -> TradeIdea | None:
    if proposal is not None and not proposal.skipped:
        idea = idea_for_symbol(proposal, symbol)
        if idea is not None:
            return idea
    # Ignore zero/weak sticky avoid|hold — those are noise and must not lock the day.
    if sticky_idea is not None and sticky_idea.action in (
        TradeAction.AVOID,
        TradeAction.HOLD,
    ):
        if sticky_idea.confidence < entry_veto_min_confidence:
            return None
    return sticky_idea


def research_veto_reason(
    proposal: ClaudeProposal | None,
    symbol: str,
    *,
    min_confidence: float,
    block_avoid: bool,
    block_hold: bool,
    require_long_approval: bool,
    sticky_idea: TradeIdea | None = None,
    entry_veto_min_confidence: float | None = None,
) -> str | None:
    """Return a human-readable veto reason, or None if entry may proceed."""
    veto_conf = (
        entry_veto_min_confidence if entry_veto_min_confidence is not None else min_confidence
    )
    idea = _effective_idea(
        proposal,
        symbol,
        sticky_idea=sticky_idea,
        entry_veto_min_confidence=veto_conf,
    )

    if idea is None:
        if require_long_approval:
            if proposal is None or proposal.skipped:
                return "research unavailable (approval required)"
            return "research did not propose this symbol"
        return None

    if block_avoid and idea.action is TradeAction.AVOID and idea.confidence >= veto_conf:
        label = "sticky " if proposal is None or proposal.skipped else ""
        return f"{label}research avoid conf={idea.confidence:.2f}"

    if block_hold and idea.action is TradeAction.HOLD and idea.confidence >= veto_conf:
        label = "sticky " if proposal is None or proposal.skipped else ""
        return f"{label}research hold conf={idea.confidence:.2f}"

    if require_long_approval:
        if idea.action is not TradeAction.LONG or idea.confidence < min_confidence:
            return f"research did not approve long (action={idea.action.value} conf={idea.confidence:.2f})"

    return None


def allows_entry_with_gates(
    proposal: ClaudeProposal | None,
    symbol: str,
    *,
    min_confidence: float,
    block_avoid: bool,
    block_hold: bool,
    require_long_approval: bool,
    sticky_idea: TradeIdea | None = None,
    entry_veto_min_confidence: float | None = None,
) -> bool:
    return research_veto_reason(
        proposal,
        symbol,
        min_confidence=min_confidence,
        block_avoid=block_avoid,
        block_hold=block_hold,
        require_long_approval=require_long_approval,
        sticky_idea=sticky_idea,
        entry_veto_min_confidence=entry_veto_min_confidence,
    ) is None
