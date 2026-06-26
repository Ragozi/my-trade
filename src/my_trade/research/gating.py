"""Research gating — when LLM ideas may block deterministic entries."""

from __future__ import annotations

from my_trade.research.models import ClaudeProposal, TradeAction, TradeIdea


def idea_for_symbol(proposal: ClaudeProposal, symbol: str) -> TradeIdea | None:
    sym = symbol.upper()
    for idea in proposal.ideas:
        if idea.symbol.upper() == sym:
            return idea
    return None


def research_veto_reason(
    proposal: ClaudeProposal | None,
    symbol: str,
    *,
    min_confidence: float,
    block_avoid: bool,
    block_hold: bool,
    require_long_approval: bool,
) -> str | None:
    """Return a human-readable veto reason, or None if entry may proceed."""
    if proposal is None or proposal.skipped:
        if require_long_approval:
            return "research unavailable (approval required)"
        return None

    idea = idea_for_symbol(proposal, symbol)
    if idea is None:
        if require_long_approval:
            return "research did not propose this symbol"
        return None

    if block_avoid and idea.action is TradeAction.AVOID and idea.confidence >= min_confidence:
        return f"research avoid conf={idea.confidence:.2f}"

    if block_hold and idea.action is TradeAction.HOLD and idea.confidence >= min_confidence:
        return f"research hold conf={idea.confidence:.2f}"

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
) -> bool:
    return research_veto_reason(
        proposal,
        symbol,
        min_confidence=min_confidence,
        block_avoid=block_avoid,
        block_hold=block_hold,
        require_long_approval=require_long_approval,
    ) is None
