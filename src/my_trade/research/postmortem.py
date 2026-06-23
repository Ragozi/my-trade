"""Optional LLM-enriched post-mortems on closed trades (budgeted)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

from my_trade.research.models import ClosedTradeReflection

_log = logging.getLogger("my_trade.research.postmortem")

POSTMORTEM_SYSTEM = """You are a trading coach reviewing a closed paper trade.
Write 2-3 concise sentences: what happened, whether the original thesis played out,
and one lesson for future similar setups. Plain text only, no JSON."""


@dataclass
class PostMortemBudget:
    max_per_day: int = 1
    calls_today: int = 0
    trading_day: str = ""

    def can_call(self, when: datetime) -> bool:
        day = when.astimezone(UTC).date().isoformat()
        if self.trading_day != day:
            self.trading_day = day
            self.calls_today = 0
        return self.calls_today < self.max_per_day

    def record(self, when: datetime) -> None:
        day = when.astimezone(UTC).date().isoformat()
        if self.trading_day != day:
            self.trading_day = day
            self.calls_today = 0
        self.calls_today += 1


class PostMortemClient:
    def reflect_on_close(
        self,
        reflection: ClosedTradeReflection,
        *,
        user_prompt: str = "",
    ) -> str: ...


@dataclass
class PostMortemGenerator:
    """Calls Claude sparingly to enrich deterministic reflections."""

    client: PostMortemClient | None
    enabled: bool = False
    budget: PostMortemBudget = field(default_factory=PostMortemBudget)

    def maybe_enrich(
        self,
        reflection: ClosedTradeReflection,
        *,
        when: datetime,
    ) -> ClosedTradeReflection:
        if not self.enabled or self.client is None:
            return reflection
        if not self.budget.can_call(when):
            _log.debug("post-mortem daily budget exhausted")
            return reflection
        prompt = (
            f"Symbol: {reflection.symbol}\n"
            f"Outcome: {reflection.outcome}\n"
            f"Exit reason: {reflection.exit_reason}\n"
            f"P&L estimate: {reflection.pnl_estimate}\n"
            f"Thesis at entry: {reflection.thesis_at_entry}\n"
            f"Deterministic summary: {reflection.summary}\n"
        )
        try:
            text = self.client.reflect_on_close(reflection, user_prompt=prompt)
            self.budget.record(when)
            return reflection.model_copy(update={"llm_summary": text.strip()})
        except Exception as exc:
            _log.warning("post-mortem LLM failed: %s", exc)
            return reflection


class MockPostMortemClient:
    def reflect_on_close(
        self,
        reflection: ClosedTradeReflection,
        *,
        user_prompt: str = "",
    ) -> str:
        del user_prompt
        return (
            f"Mock post-mortem: {reflection.symbol} {reflection.outcome} via "
            f"{reflection.exit_reason}. Consider tighter stops next time."
        )
