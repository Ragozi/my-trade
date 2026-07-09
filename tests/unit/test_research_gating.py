"""Unit tests for research entry gating (hold/avoid/approval)."""

from __future__ import annotations

from datetime import UTC, datetime

from my_trade.core.monitoring.models import ActionKind
from my_trade.core.monitoring.orchestrator import TradingOrchestrator
from my_trade.core.monitoring.store import DailyStateStore
from my_trade.core.execution import ExecutionOutcome, ExecutionStatus
from my_trade.core.risk import RiskLimits
from my_trade.core.strategy.models import ScanEvaluation, Signal
from my_trade.core.models import OrderSide
from my_trade.research.advisor import ResearchAdvisor, ResearchConfig
from my_trade.research.client import MockClaudeResearchClient
from my_trade.research.gating import allows_entry_with_gates, research_veto_reason
from my_trade.research.models import ClaudeProposal, InstrumentType, TradeAction, TradeIdea
from my_trade.research.rate_limit import ResearchRateLimiter


def _hold_proposal() -> ClaudeProposal:
    return ClaudeProposal(
        ideas=(
            TradeIdea(
                symbol="AAPL",
                action=TradeAction.HOLD,
                confidence=0.75,
                instrument=InstrumentType.SHARES,
                thesis="Earnings volatility",
            ),
        ),
        summary="hold AAPL",
    )


def test_research_veto_hold_blocks_entry() -> None:
    reason = research_veto_reason(
        _hold_proposal(),
        "AAPL",
        min_confidence=0.55,
        block_avoid=True,
        block_hold=True,
        require_long_approval=False,
    )
    assert reason is not None
    assert "hold" in reason


def test_research_hold_allowed_when_block_disabled() -> None:
    assert allows_entry_with_gates(
        _hold_proposal(),
        "AAPL",
        min_confidence=0.55,
        block_avoid=True,
        block_hold=False,
        require_long_approval=False,
    )


def test_low_confidence_avoid_blocked_with_entry_veto_threshold() -> None:
    proposal = ClaudeProposal(
        ideas=(
            TradeIdea(
                symbol="AAPL",
                action=TradeAction.AVOID,
                confidence=0.20,
                thesis="Earnings volatility",
            ),
        ),
    )
    reason = research_veto_reason(
        proposal,
        "AAPL",
        min_confidence=0.55,
        block_avoid=True,
        block_hold=True,
        require_long_approval=False,
        entry_veto_min_confidence=0.10,
    )
    assert reason is not None
    assert "avoid" in reason

    reason_old = research_veto_reason(
        proposal,
        "AAPL",
        min_confidence=0.55,
        block_avoid=True,
        block_hold=True,
        require_long_approval=False,
        entry_veto_min_confidence=0.55,
    )
    assert reason_old is None


def test_sticky_hold_blocks_when_research_skipped() -> None:
    skipped = ClaudeProposal(skipped=True, skip_reason="daily budget exhausted (10 calls)")
    sticky = TradeIdea(
        symbol="AAPL",
        action=TradeAction.AVOID,
        confidence=0.85,
        thesis="Earnings volatility",
    )
    reason = research_veto_reason(
        skipped,
        "AAPL",
        min_confidence=0.55,
        block_avoid=True,
        block_hold=True,
        require_long_approval=False,
        sticky_idea=sticky,
    )
    assert reason is not None
    assert "avoid" in reason
    assert "sticky" in reason


def test_weak_sticky_avoid_is_ignored() -> None:
    """avoid@0.00 must not lock the day when research is skipped."""
    skipped = ClaudeProposal(skipped=True, skip_reason="rate limited")
    sticky = TradeIdea(
        symbol="NVDA",
        action=TradeAction.AVOID,
        confidence=0.0,
        thesis="noise",
    )
    reason = research_veto_reason(
        skipped,
        "NVDA",
        min_confidence=0.55,
        block_avoid=True,
        block_hold=True,
        require_long_approval=False,
        sticky_idea=sticky,
        entry_veto_min_confidence=0.10,
    )
    assert reason is None


def test_sticky_not_used_when_fresh_proposal_overrides() -> None:
    skipped = ClaudeProposal(skipped=True, skip_reason="daily budget exhausted")
    sticky = TradeIdea(
        symbol="AAPL",
        action=TradeAction.AVOID,
        confidence=0.85,
        thesis="Old avoid",
    )
    fresh = ClaudeProposal(
        ideas=(
            TradeIdea(
                symbol="AAPL",
                action=TradeAction.LONG,
                confidence=0.80,
                thesis="Fresh breakout",
            ),
        )
    )
    assert allows_entry_with_gates(
        fresh,
        "AAPL",
        min_confidence=0.55,
        block_avoid=True,
        block_hold=True,
        require_long_approval=False,
        sticky_idea=sticky,
    )


def test_orchestrator_blocks_entry_on_research_hold() -> None:
    import tempfile
    from pathlib import Path

    from my_trade.core.monitoring.account import AccountSnapshot

    class _StubAccount:
        def get_snapshot(self):  # type: ignore[no-untyped-def]
            return AccountSnapshot(equity=100_000.0, cash=100_000.0, positions=())

    class _StubData:
        def get_bars(self, symbol, timeframe, limit=None):  # type: ignore[no-untyped-def]
            import pandas as pd

            return pd.DataFrame()

    class _SignalStrategy:
        def detect_entry(self, symbol, df_1m, df_5m, df_15m, now=None):  # type: ignore[no-untyped-def]
            sig = Signal(
                symbol=symbol,
                side=OrderSide.BUY,
                entry_price=100.0,
                stop_price=98.0,
                take_profit_price=103.0,
                confidence=0.83,
            )
            return sig, ScanEvaluation(eligible=True, summary="yes")

        def detect_exit(self, df_1m, entry_time, entry_price, now):  # type: ignore[no-untyped-def]
            return None

    class _StubExecution:
        def execute_entry(self, intent, account, *, now=None):  # type: ignore[no-untyped-def]
            raise AssertionError("entry should be blocked by research hold")

        def close_position(self, symbol, *, now=None):  # type: ignore[no-untyped-def]
            raise AssertionError("no close expected")

    client = MockClaudeResearchClient(ideas=_hold_proposal().ideas)
    advisor = ResearchAdvisor(
        client,
        ResearchConfig(
            enabled=True,
            block_hold_for_entry=True,
            require_approval_for_entry=False,
        ),
        rate_limiter=ResearchRateLimiter(min_interval_seconds=0, max_calls_per_day=10),
    )
    tmp = Path(tempfile.mkdtemp()) / "daily.json"
    orch = TradingOrchestrator(
        data=_StubData(),
        strategy=_SignalStrategy(),
        execution=_StubExecution(),
        account=_StubAccount(),
        store=DailyStateStore(tmp),
        limits=RiskLimits(),
        max_entries_per_symbol_per_day=1,
        symbols=("AAPL",),
        asset_class="equities",
        session_is_open=lambda _now: True,
        research_advisor=advisor,
    )
    result = orch.run_cycle(datetime(2026, 6, 25, 13, 30, tzinfo=UTC))
    assert any(
        a.kind is ActionKind.RESEARCH_NOT_APPROVED and a.symbol == "AAPL" for a in result.actions
    )
    assert not any(a.kind is ActionKind.ENTRY_SUBMITTED for a in result.actions)


def test_orchestrator_blocks_sticky_avoid_when_research_skipped() -> None:
    import tempfile
    from pathlib import Path

    from my_trade.core.monitoring.account import AccountSnapshot
    from my_trade.research.memory import ResearchMemoryStore

    class _StubAccount:
        def get_snapshot(self):  # type: ignore[no-untyped-def]
            return AccountSnapshot(equity=100_000.0, cash=100_000.0, positions=())

    class _StubData:
        def get_bars(self, symbol, timeframe, limit=None):  # type: ignore[no-untyped-def]
            import pandas as pd

            return pd.DataFrame()

    class _SignalStrategy:
        def detect_entry(self, symbol, df_1m, df_5m, df_15m, now=None):  # type: ignore[no-untyped-def]
            sig = Signal(
                symbol=symbol,
                side=OrderSide.BUY,
                entry_price=100.0,
                stop_price=98.0,
                take_profit_price=103.0,
                confidence=0.83,
            )
            return sig, ScanEvaluation(eligible=True, summary="yes")

        def detect_exit(self, df_1m, entry_time, entry_price, now):  # type: ignore[no-untyped-def]
            return None

    class _StubExecution:
        def execute_entry(self, intent, account, *, now=None):  # type: ignore[no-untyped-def]
            raise AssertionError("entry should be blocked by sticky avoid")

        def close_position(self, symbol, *, now=None):  # type: ignore[no-untyped-def]
            raise AssertionError("no close expected")

    class _BudgetExhaustedAdvisor:
        config = ResearchConfig(
            enabled=True,
            block_avoid_for_entry=True,
            block_hold_for_entry=True,
            require_approval_for_entry=False,
        )

        def is_active_for(self, asset_class: str) -> bool:
            return True

        def propose(self, context, *, when):  # type: ignore[no-untyped-def]
            from my_trade.research.models import ResearchResult

            return ResearchResult(
                proposal=ClaudeProposal(
                    skipped=True, skip_reason="daily budget exhausted (10 calls)"
                ),
                called_api=False,
                rate_limited=True,
            )

        def allows_entry(self, symbol, proposal, *, sticky_idea=None):  # type: ignore[no-untyped-def]
            return allows_entry_with_gates(
                proposal,
                symbol,
                min_confidence=0.55,
                block_avoid=True,
                block_hold=True,
                require_long_approval=False,
                sticky_idea=sticky_idea,
            )

        def entry_veto_reason(self, symbol, proposal, *, sticky_idea=None):  # type: ignore[no-untyped-def]
            return research_veto_reason(
                proposal,
                symbol,
                min_confidence=0.55,
                block_avoid=True,
                block_hold=True,
                require_long_approval=False,
                sticky_idea=sticky_idea,
            )

    mem_path = Path(tempfile.mkdtemp()) / "memory.json"
    memory = ResearchMemoryStore(mem_path)
    memory.note_proposals(
        (
            TradeIdea(
                symbol="AAPL",
                action=TradeAction.AVOID,
                confidence=0.85,
                thesis="Earnings volatility",
            ),
        )
    )
    tmp = Path(tempfile.mkdtemp()) / "daily.json"
    orch = TradingOrchestrator(
        data=_StubData(),
        strategy=_SignalStrategy(),
        execution=_StubExecution(),
        account=_StubAccount(),
        store=DailyStateStore(tmp),
        limits=RiskLimits(),
        max_entries_per_symbol_per_day=1,
        symbols=("AAPL",),
        asset_class="equities",
        session_is_open=lambda _now: True,
        research_advisor=_BudgetExhaustedAdvisor(),
        research_memory=memory,
    )
    result = orch.run_cycle(datetime(2026, 7, 1, 15, 0, tzinfo=UTC))
    assert any(
        a.kind is ActionKind.RESEARCH_NOT_APPROVED and a.symbol == "AAPL" for a in result.actions
    )
    assert not any(a.kind is ActionKind.ENTRY_SUBMITTED for a in result.actions)


def test_orchestrator_submits_only_one_entry_per_cycle() -> None:
    import tempfile
    from pathlib import Path

    from my_trade.core.monitoring.account import AccountSnapshot

    class _StubAccount:
        def get_snapshot(self):  # type: ignore[no-untyped-def]
            return AccountSnapshot(equity=100_000.0, cash=100_000.0, positions=())

    class _StubData:
        def get_bars(self, symbol, timeframe, limit=None):  # type: ignore[no-untyped-def]
            import pandas as pd

            return pd.DataFrame()

    class _SignalStrategy:
        def detect_entry(self, symbol, df_1m, df_5m, df_15m, now=None):  # type: ignore[no-untyped-def]
            sig = Signal(
                symbol=symbol,
                side=OrderSide.BUY,
                entry_price=100.0,
                stop_price=98.0,
                take_profit_price=103.0,
                confidence=0.83,
            )
            return sig, ScanEvaluation(eligible=True, summary="yes")

        def detect_exit(self, df_1m, entry_time, entry_price, now):  # type: ignore[no-untyped-def]
            return None

    submitted: list[str] = []

    class _StubExecution:
        def execute_entry(self, intent, account, *, now=None):  # type: ignore[no-untyped-def]
            submitted.append(intent.symbol)
            return ExecutionOutcome(
                status=ExecutionStatus.SUBMITTED,
                client_order_id="cid",
                submitted=True,
            )

        def close_position(self, symbol, *, now=None):  # type: ignore[no-untyped-def]
            raise AssertionError("no close expected")

    tmp = Path(tempfile.mkdtemp()) / "daily.json"
    orch = TradingOrchestrator(
        data=_StubData(),
        strategy=_SignalStrategy(),
        execution=_StubExecution(),
        account=_StubAccount(),
        store=DailyStateStore(tmp),
        limits=RiskLimits(max_concurrent_positions=1),
        max_entries_per_symbol_per_day=1,
        symbols=("AAPL", "MSFT"),
        asset_class="equities",
        session_is_open=lambda _now: True,
    )
    result = orch.run_cycle(datetime(2026, 7, 1, 15, 0, tzinfo=UTC))
    assert len(submitted) == 1
    assert sum(1 for a in result.actions if a.kind is ActionKind.ENTRY_SUBMITTED) == 1
