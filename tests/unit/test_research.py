"""Unit tests for the Claude research layer (no live API calls)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from my_trade.config import load_settings
from my_trade.core.monitoring.models import ActionKind
from my_trade.core.monitoring.orchestrator import TradingOrchestrator
from my_trade.core.monitoring.store import DailyStateStore
from my_trade.core.risk import RiskLimits
from my_trade.core.strategy.models import ScanEvaluation, Signal
from my_trade.core.models import OrderSide
from my_trade.research.advisor import ResearchAdvisor, ResearchConfig
from my_trade.research.client import MockClaudeResearchClient, extract_json_object
from my_trade.research.context import build_research_context
from my_trade.research.models import InstrumentType, TradeAction, TradeIdea
from my_trade.research.rate_limit import ResearchRateLimiter


class _StubAccount:
    def get_snapshot(self):  # type: ignore[no-untyped-def]
        from my_trade.core.monitoring.account import AccountSnapshot

        return AccountSnapshot(equity=100_000.0, cash=100_000.0, positions=())


class _StubData:
    def get_bars(self, symbol: str, timeframe: str, limit: int | None = None):  # type: ignore[no-untyped-def]
        import pandas as pd

        return pd.DataFrame()


class _StubStrategy:
    def detect_entry(self, symbol, df_1m, df_5m, df_15m, now=None):  # type: ignore[no-untyped-def]
        return None, ScanEvaluation(eligible=False, summary="stub no signal")

    def detect_exit(self, df_1m, entry_time, entry_price, now):  # type: ignore[no-untyped-def]
        return None


class _StubExecution:
    def execute_entry(self, intent, account, *, now=None):  # type: ignore[no-untyped-def]
        raise AssertionError("should not execute in research-only tests")

    def close_position(self, symbol, *, now=None):  # type: ignore[no-untyped-def]
        raise AssertionError("should not close in research-only tests")


def _orchestrator(research: ResearchAdvisor | None) -> TradingOrchestrator:
    import tempfile
    from pathlib import Path

    tmp = Path(tempfile.mkdtemp()) / "daily.json"
    return TradingOrchestrator(
        data=_StubData(),
        strategy=_StubStrategy(),
        execution=_StubExecution(),
        account=_StubAccount(),
        store=DailyStateStore(tmp),
        limits=RiskLimits(),
        symbols=("AAPL", "MSFT"),
        asset_class="equities",
        session_is_open=lambda _now: True,
        research_advisor=research,
    )


def test_extract_json_object_strips_fence() -> None:
    raw = extract_json_object('```json\n{"summary": "ok", "ideas": []}\n```')
    assert raw["summary"] == "ok"


def test_rate_limiter_blocks_until_interval() -> None:
    limiter = ResearchRateLimiter(min_interval_seconds=300, max_calls_per_day=10)
    t0 = datetime(2026, 6, 20, 14, 0, tzinfo=UTC)
    assert limiter.can_call(t0) is True
    limiter.record_call(t0)
    assert limiter.can_call(t0) is False
    assert limiter.seconds_until_allowed(t0) == 300.0


def test_rate_limiter_blocks_after_failed_attempt() -> None:
    limiter = ResearchRateLimiter(min_interval_seconds=300, max_calls_per_day=10)
    t0 = datetime(2026, 6, 20, 14, 0, tzinfo=UTC)
    limiter.record_call(t0)
    assert limiter.can_call(t0) is False


def test_billing_failure_sets_extended_cooldown() -> None:
    limiter = ResearchRateLimiter(min_interval_seconds=60, max_calls_per_day=10)
    t0 = datetime(2026, 6, 20, 14, 0, tzinfo=UTC)
    limiter.record_billing_failure(t0, cooldown_seconds=3600)
    assert limiter.can_call(t0) is False
    assert "billing cooldown" in limiter.skip_reason(t0)


def test_advisor_skipped_when_disabled() -> None:
    client = MockClaudeResearchClient()
    advisor = ResearchAdvisor(
        client,
        ResearchConfig(enabled=False),
        rate_limiter=ResearchRateLimiter(min_interval_seconds=0, max_calls_per_day=10),
    )
    ctx = build_research_context(
        snapshot=_StubAccount().get_snapshot(),
        candidate_symbols=("AAPL",),
        asset_class="equities",
        session_open=True,
        as_of=datetime.now(UTC),
        equity=100_000.0,
        day_pnl=0.0,
        peak_equity=100_000.0,
    )
    result = advisor.propose(ctx, when=datetime.now(UTC))
    assert result.proposal.skipped is True
    assert client.call_count == 0


def test_advisor_returns_mock_ideas() -> None:
    idea = TradeIdea(
        symbol="MSFT",
        action=TradeAction.LONG,
        confidence=0.8,
        instrument=InstrumentType.SHARES,
        thesis="Cloud growth",
    )
    client = MockClaudeResearchClient(ideas=(idea,))
    advisor = ResearchAdvisor(
        client,
        ResearchConfig(enabled=True, min_confidence=0.5),
        rate_limiter=ResearchRateLimiter(min_interval_seconds=0, max_calls_per_day=10),
    )
    ctx = build_research_context(
        snapshot=_StubAccount().get_snapshot(),
        candidate_symbols=("MSFT",),
        asset_class="equities",
        session_open=True,
        as_of=datetime.now(UTC),
        equity=100_000.0,
        day_pnl=0.0,
        peak_equity=100_000.0,
    )
    result = advisor.propose(ctx, when=datetime.now(UTC))
    assert result.called_api is True
    assert len(result.proposal.ideas) == 1
    assert result.proposal.ideas[0].symbol == "MSFT"


def test_orchestrator_logs_research_proposals() -> None:
    idea = TradeIdea(
        symbol="AAPL",
        action=TradeAction.LONG,
        confidence=0.9,
        instrument=InstrumentType.SHARES,
        thesis="Test thesis",
    )
    client = MockClaudeResearchClient(ideas=(idea,))
    advisor = ResearchAdvisor(
        client,
        ResearchConfig(enabled=True, require_approval_for_entry=False),
        rate_limiter=ResearchRateLimiter(min_interval_seconds=0, max_calls_per_day=10),
    )
    orch = _orchestrator(advisor)
    result = orch.run_cycle(datetime(2026, 6, 20, 15, 0, tzinfo=UTC))
    kinds = {a.kind for a in result.actions}
    assert ActionKind.RESEARCH_PROPOSAL in kinds
    assert any(a.symbol == "AAPL" for a in result.actions)


def test_require_approval_blocks_unlisted_symbol(monkeypatch: pytest.MonkeyPatch) -> None:
    idea = TradeIdea(
        symbol="AAPL",
        action=TradeAction.LONG,
        confidence=0.9,
        instrument=InstrumentType.SHARES,
        thesis="Only AAPL",
    )
    client = MockClaudeResearchClient(ideas=(idea,))
    advisor = ResearchAdvisor(
        client,
        ResearchConfig(enabled=True, require_approval_for_entry=True, min_confidence=0.5),
        rate_limiter=ResearchRateLimiter(min_interval_seconds=0, max_calls_per_day=10),
    )

    class _SignalStrategy(_StubStrategy):
        def detect_entry(self, symbol, df_1m, df_5m, df_15m, now=None):  # type: ignore[no-untyped-def]
            sig = Signal(
                symbol=symbol,
                side=OrderSide.BUY,
                entry_price=100.0,
                stop_price=98.0,
                take_profit_price=103.0,
                confidence=1.0,
            )
            return sig, ScanEvaluation(eligible=True, summary="yes")

    import tempfile
    from pathlib import Path

    tmp = Path(tempfile.mkdtemp()) / "daily.json"
    orch = TradingOrchestrator(
        data=_StubData(),
        strategy=_SignalStrategy(),
        execution=_StubExecution(),
        account=_StubAccount(),
        store=DailyStateStore(tmp),
        limits=RiskLimits(),
        symbols=("MSFT",),
        asset_class="equities",
        session_is_open=lambda _now: True,
        research_advisor=advisor,
    )
    result = orch.run_cycle(datetime(2026, 6, 20, 15, 0, tzinfo=UTC))
    assert any(a.kind is ActionKind.RESEARCH_NOT_APPROVED and a.symbol == "MSFT" for a in result.actions)
    assert not any(a.kind is ActionKind.ENTRY_SUBMITTED for a in result.actions)


def test_settings_loads_enable_claude() -> None:
    s = load_settings(
        {
            "ENABLE_CLAUDE": "true",
            "ANTHROPIC_API_KEY": "test-key",
            "ASSET_CLASS": "equities",
            "APCA_API_KEY_ID": "k",
            "APCA_API_SECRET_KEY": "s",
        }
    )
    assert s.research.enabled is True
    assert s.research.api_key == "test-key"


def test_validate_requires_anthropic_key_when_claude_enabled() -> None:
    s = load_settings(
        {
            "ENABLE_CLAUDE": "true",
            "ANTHROPIC_API_KEY": "",
            "ASSET_CLASS": "equities",
            "APCA_API_KEY_ID": "k",
            "APCA_API_SECRET_KEY": "s",
        }
    )
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        s.validate_for_trading()


def test_research_disabled_builds_nothing() -> None:
    from my_trade.research import (
        build_research_advisor,
        build_research_evaluation,
        build_research_memory,
        research_is_active,
    )

    s = load_settings(
        {
            "ENABLE_CLAUDE": "false",
            "ASSET_CLASS": "equities",
            "APCA_API_KEY_ID": "k",
            "APCA_API_SECRET_KEY": "s",
        }
    )
    assert research_is_active(s) is False
    assert build_research_advisor(s) is None
    assert build_research_memory(s) is None
    assert build_research_evaluation(s) is None
