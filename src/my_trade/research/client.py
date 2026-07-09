"""Anthropic API client for structured equity research proposals."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from typing import Any, Protocol

from my_trade.research.models import ClaudeProposal, InstrumentType, TradeAction, TradeIdea
from my_trade.research.prompts import SYSTEM_PROMPT, build_user_prompt

_log = logging.getLogger("my_trade.research.client")


class ResearchClient(Protocol):
    def propose_equity_ideas(
        self,
        context: Any,
        *,
        max_ideas: int,
    ) -> ClaudeProposal: ...


def _parse_proposal(raw: dict[str, Any], *, model: str, latency_ms: float) -> ClaudeProposal:
    ideas: list[TradeIdea] = []
    for item in raw.get("ideas") or []:
        if not isinstance(item, dict):
            continue
        try:
            ideas.append(
                TradeIdea(
                    symbol=str(item.get("symbol", "")),
                    action=TradeAction(str(item.get("action", "hold")).lower()),
                    confidence=float(item.get("confidence", 0.0)),
                    instrument=InstrumentType(str(item.get("instrument", "shares")).lower()),
                    thesis=str(item.get("thesis", "")),
                    time_horizon=item.get("time_horizon", "swing"),  # type: ignore[arg-type]
                    suggested_stop_pct=item.get("suggested_stop_pct"),
                    suggested_target_pct=item.get("suggested_target_pct"),
                    catalysts=tuple(str(c) for c in (item.get("catalysts") or [])),
                    risks=tuple(str(r) for r in (item.get("risks") or [])),
                )
            )
        except (ValueError, TypeError) as exc:
            _log.debug("skip invalid idea %s: %s", item, exc)
    return ClaudeProposal(
        ideas=tuple(ideas),
        summary=str(raw.get("summary", "")),
        model=model,
        latency_ms=latency_ms,
    )


def extract_json_object(text: str) -> dict[str, Any]:
    """Best-effort JSON extraction from model output."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        body = lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
        text = "\n".join(body).strip()
        if text.lower().startswith("json"):
            text = text[4:].strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object found in Claude response")
    return json.loads(text[start : end + 1])


class ClaudeResearchClient:
    """Calls Anthropic Messages API and validates structured proposals."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "claude-sonnet-4-6",
        max_tokens: int = 4096,
        timeout_seconds: float = 60.0,
        message_fn: Callable[..., Any] | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY is required when Claude research is enabled")
        self._api_key = api_key
        self._model = model
        self._max_tokens = max_tokens
        self._timeout = timeout_seconds
        self._message_fn = message_fn

    @property
    def model(self) -> str:
        return self._model

    def propose_equity_ideas(
        self,
        context: Any,
        *,
        max_ideas: int,
    ) -> ClaudeProposal:
        from my_trade.research.models import ResearchContext

        if not isinstance(context, ResearchContext):
            raise TypeError("context must be ResearchContext")

        user_prompt = build_user_prompt(context, max_ideas=max_ideas)
        started = time.perf_counter()
        text = self._call_messages(user_prompt)
        latency_ms = (time.perf_counter() - started) * 1000.0
        raw = extract_json_object(text)
        return _parse_proposal(raw, model=self._model, latency_ms=latency_ms).model_copy(
            update={"provider": "claude"}
        )

    def reflect_on_close(
        self,
        reflection: object,
        *,
        user_prompt: str,
    ) -> str:
        from my_trade.research.models import ClosedTradeReflection
        from my_trade.research.postmortem import POSTMORTEM_SYSTEM

        if not isinstance(reflection, ClosedTradeReflection):
            raise TypeError("reflection must be ClosedTradeReflection")
        del reflection
        return self._call_messages(
            user_prompt,
            system=POSTMORTEM_SYSTEM,
            max_tokens=min(512, self._max_tokens),
        )

    def _call_messages(
        self,
        user_prompt: str,
        *,
        system: str = SYSTEM_PROMPT,
        max_tokens: int | None = None,
    ) -> str:
        if self._message_fn is not None:
            return str(self._message_fn(user_prompt))

        try:
            import anthropic
        except ImportError as exc:
            raise RuntimeError(
                "anthropic package is required for Claude research; pip install anthropic"
            ) from exc

        client = anthropic.Anthropic(api_key=self._api_key, timeout=self._timeout)
        response = client.messages.create(
            model=self._model,
            max_tokens=max_tokens or self._max_tokens,
            system=system,
            messages=[{"role": "user", "content": user_prompt}],
        )
        parts: list[str] = []
        for block in response.content:
            text = getattr(block, "text", None)
            if text:
                parts.append(text)
        if not parts:
            raise ValueError("empty Claude response")
        return "\n".join(parts)


class MockClaudeResearchClient:
    """Deterministic client for tests and offline development."""

    def __init__(self, ideas: tuple[TradeIdea, ...] | None = None) -> None:
        self._ideas = ideas or (
            TradeIdea(
                symbol="AAPL",
                action=TradeAction.LONG,
                confidence=0.72,
                instrument=InstrumentType.SHARES,
                thesis="Mock: strong trend, advisory only.",
                time_horizon="swing",
            ),
        )
        self.call_count = 0

    def propose_equity_ideas(
        self,
        context: Any,
        *,
        max_ideas: int,
    ) -> ClaudeProposal:
        del context
        self.call_count += 1
        return ClaudeProposal(
            ideas=self._ideas[:max_ideas],
            summary="Mock research proposal",
            model="mock-claude",
            provider="mock",
            latency_ms=1.0,
        )

    def reflect_on_close(
        self,
        reflection: object,
        *,
        user_prompt: str = "",
    ) -> str:
        del user_prompt
        from my_trade.research.models import ClosedTradeReflection

        if isinstance(reflection, ClosedTradeReflection):
            return f"Mock LLM post-mortem for {reflection.symbol} ({reflection.outcome})."
        return "Mock post-mortem."
