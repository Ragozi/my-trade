"""OpenAI and xAI (Grok) research clients — same JSON contract as Claude."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from my_trade.research.client import _parse_proposal, extract_json_object
from my_trade.research.models import ClaudeProposal, ResearchContext
from my_trade.research.prompts import SYSTEM_PROMPT, build_user_prompt

_log = logging.getLogger("my_trade.research.providers")


class OpenAIResearchClient:
    """Calls OpenAI Chat Completions with JSON response format."""

    provider = "openai"

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "gpt-4o-mini",
        max_tokens: int = 2048,
        timeout_seconds: float = 60.0,
        completion_fn: Callable[..., Any] | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required when workhorse provider is openai")
        self._api_key = api_key
        self._model = model
        self._max_tokens = max_tokens
        self._timeout = timeout_seconds
        self._completion_fn = completion_fn

    @property
    def model(self) -> str:
        return self._model

    def propose_equity_ideas(
        self,
        context: ResearchContext,
        *,
        max_ideas: int,
    ) -> ClaudeProposal:
        user_prompt = build_user_prompt(context, max_ideas=max_ideas)
        started = time.perf_counter()
        text = self._call_chat(user_prompt)
        latency_ms = (time.perf_counter() - started) * 1000.0
        raw = extract_json_object(text)
        proposal = _parse_proposal(raw, model=self._model, latency_ms=latency_ms)
        return proposal.model_copy(update={"provider": self.provider})

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
        return self._call_chat(user_prompt, system=POSTMORTEM_SYSTEM, max_tokens=512)

    def _call_chat(
        self,
        user_prompt: str,
        *,
        system: str = SYSTEM_PROMPT,
        max_tokens: int | None = None,
    ) -> str:
        if self._completion_fn is not None:
            return str(self._completion_fn(user_prompt))

        try:
            import openai
        except ImportError as exc:
            raise RuntimeError(
                "openai package is required for OpenAI research; pip install openai"
            ) from exc

        client = openai.OpenAI(api_key=self._api_key, timeout=self._timeout)
        response = client.chat.completions.create(
            model=self._model,
            max_tokens=max_tokens or self._max_tokens,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_prompt},
            ],
        )
        text = response.choices[0].message.content if response.choices else None
        if not text:
            raise ValueError("empty OpenAI response")
        return text


class XAIResearchClient:
    """Calls xAI Grok via OpenAI-compatible API."""

    provider = "xai"
    _BASE_URL = "https://api.x.ai/v1"

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "grok-2-1212",
        max_tokens: int = 2048,
        timeout_seconds: float = 60.0,
        completion_fn: Callable[..., Any] | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("XAI_API_KEY is required when workhorse provider is xai")
        self._api_key = api_key
        self._model = model
        self._max_tokens = max_tokens
        self._timeout = timeout_seconds
        self._completion_fn = completion_fn

    @property
    def model(self) -> str:
        return self._model

    def propose_equity_ideas(
        self,
        context: ResearchContext,
        *,
        max_ideas: int,
    ) -> ClaudeProposal:
        user_prompt = build_user_prompt(context, max_ideas=max_ideas)
        started = time.perf_counter()
        text = self._call_chat(user_prompt)
        latency_ms = (time.perf_counter() - started) * 1000.0
        raw = extract_json_object(text)
        proposal = _parse_proposal(raw, model=self._model, latency_ms=latency_ms)
        return proposal.model_copy(update={"provider": self.provider})

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
        return self._call_chat(user_prompt, system=POSTMORTEM_SYSTEM, max_tokens=512)

    def _call_chat(
        self,
        user_prompt: str,
        *,
        system: str = SYSTEM_PROMPT,
        max_tokens: int | None = None,
    ) -> str:
        if self._completion_fn is not None:
            return str(self._completion_fn(user_prompt))

        try:
            import openai
        except ImportError as exc:
            raise RuntimeError(
                "openai package is required for xAI research; pip install openai"
            ) from exc

        client = openai.OpenAI(
            api_key=self._api_key,
            base_url=self._BASE_URL,
            timeout=self._timeout,
        )
        response = client.chat.completions.create(
            model=self._model,
            max_tokens=max_tokens or self._max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_prompt},
            ],
        )
        text = response.choices[0].message.content if response.choices else None
        if not text:
            raise ValueError("empty xAI response")
        return text
