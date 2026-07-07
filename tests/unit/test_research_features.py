"""Tests for portfolio-aware prompts, evaluation, and post-mortem."""

from __future__ import annotations

from datetime import UTC, datetime

from my_trade.core.monitoring.models import ActionKind
from my_trade.core.monitoring.orchestrator import TradingOrchestrator
from my_trade.core.monitoring.store import DailyStateStore
from my_trade.core.risk import RiskLimits
from my_trade.core.strategy.models import ScanEvaluation, Signal
from my_trade.core.models import OrderSide
from my_trade.research.advisor import ResearchAdvisor, ResearchConfig
from my_trade.research.client import MockClaudeResearchClient
from my_trade.research.context import build_research_context
from my_trade.research.evaluation import ResearchEvaluationStore
from my_trade.research.memory import ResearchMemoryStore
from my_trade.research.models import (
    InstrumentType,
    OpenPositionSummary,
    TradeAction,
    TradeIdea,
)
from my_trade.research.portfolio import build_portfolio_snapshot
from my_trade.research.postmortem import MockPostMortemClient, PostMortemBudget, PostMortemGenerator
from my_trade.research.prompts import build_user_prompt
from my_trade.research.rate_limit import ResearchRateLimiter


class _StubAccount:
    def get_snapshot(self):  # type: ignore[no-untyped-def]
        from my_trade.core.monitoring.account import AccountSnapshot, Position

        return AccountSnapshot(
            equity=100_000.0,
            cash=50_000.0,
            positions=(
                Position(
                    symbol="AAPL",
                    qty=100.0,
                    avg_entry_price=150.0,
                    market_value=15_000.0,
                    unrealized_pl=500.0,
                ),
                Position(
                    symbol="MSFT",
                    qty=50.0,
                    avg_entry_price=400.0,
                    market_value=20_000.0,
                    unrealized_pl=200.0,
                ),
            ),
        )


class _StubData:
    def get_bars(self, symbol: str, timeframe: str, limit: int | None = None):  # type: ignore[no-untyped-def]
        import pandas as pd

        return pd.DataFrame()


class _StubStrategy:
    def detect_entry(self, symbol, df_1m, df_5m, df_15m, now=None):  # type: ignore[no-untyped-def]
        if symbol.upper() == "NVDA":
            sig = Signal(
                symbol=symbol,
                side=OrderSide.BUY,
                entry_price=100.0,
                stop_price=98.0,
                take_profit_price=103.0,
                confidence=1.0,
            )
            return sig, ScanEvaluation(eligible=True, summary="yes")
        return None, ScanEvaluation(eligible=False, summary="no")

    def detect_exit(self, df_1m, entry_time, entry_price, now):  # type: ignore[no-untyped-def]
        return None


class _StubExecution:
    def execute_entry(self, intent, account, *, now=None):  # type: ignore[no-untyped-def]
        from my_trade.core.execution import ExecutionOutcome, ExecutionStatus

        return ExecutionOutcome(
            submitted=True,
            status=ExecutionStatus.SUBMITTED,
            detail="ok",
            client_order_id="test-order",
        )

    def close_position(self, symbol, *, now=None):  # type: ignore[no-untyped-def]
        raise AssertionError("not used")


def test_portfolio_snapshot_warns_on_concentration() -> None:
    positions = (
        OpenPositionSummary(
            symbol="AAPL",
            qty=100,
            avg_entry_price=150,
            market_value=30_000,
            unrealized_pl=0,
        ),
        OpenPositionSummary(
            symbol="MSFT",
            qty=50,
            avg_entry_price=400,
            market_value=15_000,
            unrealized_pl=0,
        ),
    )
    snap = build_portfolio_snapshot(positions, equity=100_000, candidate_symbols=("NVDA",))
    assert snap.largest_sector == "Technology"
    assert snap.largest_sector_weight_pct == 0.45
    assert any("Technology" in w for w in snap.concentration_warnings)
    assert any("NVDA" in w for w in snap.concentration_warnings)


def test_prompt_includes_portfolio_and_comparison() -> None:
    from my_trade.core.monitoring.account import AccountSnapshot
    from my_trade.research.models import ComparisonSummary

    ctx = build_research_context(
        snapshot=AccountSnapshot(equity=100_000.0),
        candidate_symbols=("AAPL",),
        asset_class="equities",
        session_open=True,
        as_of=datetime(2026, 6, 20, 15, 0, tzinfo=UTC),
        equity=100_000.0,
        day_pnl=0.0,
        peak_equity=100_000.0,
        comparison_summary=ComparisonSummary(sample_cycles=10, both_agree=3),
    )
    prompt = build_user_prompt(ctx, max_ideas=2)
    assert "portfolio_snapshot" in prompt
    assert "claude_vs_strategy" in prompt
    assert "both_agree" in prompt


def test_evaluation_records_alignment(tmp_path) -> None:
    store = ResearchEvaluationStore(tmp_path / "eval.json")
    idea = TradeIdea(
        symbol="AAPL",
        action=TradeAction.LONG,
        confidence=0.8,
        instrument=InstrumentType.SHARES,
        thesis="test",
    )
    from my_trade.research.models import ClaudeProposal

    proposal = ClaudeProposal(ideas=(idea,), summary="ok", model="mock")
    when = datetime(2026, 6, 20, 15, 0, tzinfo=UTC)
    store.record_cycle(
        when=when,
        symbols=("AAPL", "MSFT"),
        proposal=proposal,
        strategy_signals={"AAPL": True, "MSFT": False},
        min_confidence=0.55,
    )
    summary = store.summary(window=10)
    assert summary.sample_cycles == 2
    assert summary.both_agree == 1
    assert summary.both_pass == 1


def test_postmortem_budget_limits_llm_calls(tmp_path) -> None:
    client = MockPostMortemClient()
    gen = PostMortemGenerator(
        client=client,
        enabled=True,
        budget=PostMortemBudget(max_per_day=1),
    )
    store = ResearchMemoryStore(tmp_path / "mem.json", postmortem=gen)

    when = datetime(2026, 6, 20, 15, 0, tzinfo=UTC)
    r1 = store.record_close(
        symbol="AAPL",
        exit_reason="stop_loss",
        entry_price=100,
        qty=10,
        unrealized_pl=-20,
        closed_at=when,
    )
    r2 = store.record_close(
        symbol="MSFT",
        exit_reason="take_profit",
        entry_price=200,
        qty=5,
        unrealized_pl=30,
        closed_at=when,
    )
    assert r1.llm_summary
    assert not r2.llm_summary


def test_orchestrator_records_evaluation_on_entry(tmp_path) -> None:
    ideas = (
        TradeIdea(
            symbol="NVDA",
            action=TradeAction.LONG,
            confidence=0.9,
            instrument=InstrumentType.SHARES,
            thesis="AI momentum",
        ),
    )
    client = MockClaudeResearchClient(ideas=ideas)
    advisor = ResearchAdvisor(
        client,
        ResearchConfig(enabled=True, require_approval_for_entry=False),
        rate_limiter=ResearchRateLimiter(min_interval_seconds=0, max_calls_per_day=10),
    )
    eval_path = tmp_path / "eval.json"
    evaluation = ResearchEvaluationStore(eval_path)
    orch = TradingOrchestrator(
        data=_StubData(),
        strategy=_StubStrategy(),
        execution=_StubExecution(),
        account=_StubAccount(),
        store=DailyStateStore(tmp_path / "daily.json"),
        limits=RiskLimits(max_concurrent_positions=3),
        symbols=("NVDA", "AAPL"),
        asset_class="equities",
        session_is_open=lambda _now: True,
        research_advisor=advisor,
        research_evaluation=evaluation,
    )
    result = orch.run_cycle(datetime(2026, 6, 20, 15, 0, tzinfo=UTC))
    assert any(a.kind is ActionKind.ENTRY_SUBMITTED for a in result.actions)
    summary = evaluation.summary()
    assert summary.entries_tracked >= 1
