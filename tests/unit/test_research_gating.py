"""Unit tests for research entry gating (hold/avoid/approval)."""

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


def test_skipped_research_blocks_when_entry_gates_enabled() -> None:
    skipped = ClaudeProposal(skipped=True, skip_reason="rate limited")

    reason = research_veto_reason(
        skipped,
        "AAPL",
        min_confidence=0.55,
        block_avoid=True,
        block_hold=False,
        require_long_approval=False,
    )

    assert reason is not None
    assert "unavailable" in reason
    assert allows_entry_with_gates(
        skipped,
        "AAPL",
        min_confidence=0.55,
        block_avoid=False,
        block_hold=False,
        require_long_approval=False,
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


def test_orchestrator_reuses_last_research_veto_when_rate_limited() -> None:
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
            raise AssertionError("entry should stay blocked by cached research hold")

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
        rate_limiter=ResearchRateLimiter(min_interval_seconds=300, max_calls_per_day=10),
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
    first = orch.run_cycle(datetime(2026, 6, 25, 13, 30, tzinfo=UTC))
    second = orch.run_cycle(datetime(2026, 6, 25, 13, 31, tzinfo=UTC))

    assert client.call_count == 1
    assert any(a.kind is ActionKind.RESEARCH_NOT_APPROVED for a in first.actions)
    assert any(a.kind is ActionKind.RESEARCH_SKIPPED for a in second.actions)
    assert any(
        a.kind is ActionKind.RESEARCH_NOT_APPROVED and a.symbol == "AAPL" for a in second.actions
    )
    assert not any(a.kind is ActionKind.ENTRY_SUBMITTED for a in second.actions)
