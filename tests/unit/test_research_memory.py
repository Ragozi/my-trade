"""Tests for research memory, reflection, and history."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

from my_trade.observability.journal import Journal
from my_trade.research.context import build_research_context
from my_trade.research.history import (
    all_closed_trades_from_events,
    classify_outcome,
    compute_performance,
    infer_broker_closes_from_events,
    pair_trades_from_events,
)
from my_trade.research.memory import ResearchMemoryStore
from my_trade.research.models import ClosedTradeReflection, TradeAction, TradeIdea
from my_trade.research.prompts import build_user_prompt
from my_trade.research.reflection import build_reflection


def test_classify_outcome_from_exit_reason() -> None:
    assert classify_outcome("take_profit", None) == "win"
    assert classify_outcome("stop_loss", None) == "loss"
    assert classify_outcome("broker_bracket_stop", None) == "loss"
    assert classify_outcome("broker_close", None) == "loss"
    assert classify_outcome("time_stop", None) == "flat"


def test_build_reflection_win_on_profit() -> None:
    ref = build_reflection(
        symbol="AAPL",
        exit_reason="take_profit",
        entry_price=100.0,
        qty=10.0,
        unrealized_pl=25.0,
        thesis_at_entry="Breakout above resistance",
        closed_at=datetime(2026, 6, 20, 15, 0, tzinfo=UTC),
    )
    assert ref.outcome == "win"
    assert ref.pnl_estimate == 25.0
    assert "AAPL" in ref.summary
    assert "Breakout" in ref.summary


def test_memory_store_persists_reflection(tmp_path: Path) -> None:
    path = tmp_path / "memory.json"
    store = ResearchMemoryStore(path, max_reflections=10)
    store.note_proposals(
        (
            TradeIdea(
                symbol="MSFT",
                action=TradeAction.LONG,
                confidence=0.8,
                thesis="AI cloud momentum",
            ),
        )
    )
    ref = store.record_close(
        symbol="MSFT",
        exit_reason="stop_loss",
        entry_price=400.0,
        qty=5.0,
        unrealized_pl=-50.0,
        closed_at=datetime(2026, 6, 20, 16, 0, tzinfo=UTC),
    )
    assert ref.outcome == "loss"
    assert "AI cloud" in ref.thesis_at_entry

    reloaded = ResearchMemoryStore(path)
    assert len(reloaded._reflections) == 1
    assert reloaded._reflections[0].symbol == "MSFT"


def test_pair_trades_from_journal(tmp_path: Path) -> None:
    db = tmp_path / "journal.db"
    journal = Journal(db)
    journal.record_event(
        "research_proposal",
        symbol="AAPL",
        detail="long conf=0.80 shares swing: Earnings beat setup",
    )
    journal.record_event(
        "entry_submitted",
        symbol="AAPL",
        detail="entry=100.00 stop=98.00 tp=103.00 conf=0.90",
        equity=100_000.0,
    )
    journal.record_event(
        "exit_submitted",
        symbol="AAPL",
        detail="take_profit",
        equity=100_050.0,
    )
    events = list(journal.fetch_all())
    journal.close()

    outcomes = pair_trades_from_events(events, symbols=frozenset({"AAPL"}))
    assert len(outcomes) == 1
    assert outcomes[0].exit_reason == "take_profit"
    assert outcomes[0].thesis_at_entry.startswith("Earnings")


def test_infer_broker_close_from_exit_failed(tmp_path: Path) -> None:
    db = tmp_path / "journal.db"
    journal = Journal(db)
    journal.record_event(
        "entry_submitted",
        symbol="AAPL",
        detail="entry=280.00 stop=278.20 tp=284.76 conf=0.83",
    )
    journal.record_event(
        "exit_failed",
        symbol="AAPL",
        detail=(
            'close failed: {"held_for_orders":"1067",'
            '"message":"insufficient qty available for order"}'
        ),
        day_pnl=-6000.0,
    )
    events = list(journal.fetch_all())
    journal.close()

    inferred = infer_broker_closes_from_events(events, symbols=frozenset({"AAPL"}))
    assert len(inferred) == 1
    assert inferred[0].exit_reason == "broker_bracket_stop"

    all_outcomes = all_closed_trades_from_events(events, symbols=frozenset({"AAPL"}))
    assert len(all_outcomes) == 1


def test_sync_from_journal_adds_inferred_close(tmp_path: Path) -> None:
    db = tmp_path / "journal.db"
    journal = Journal(db)
    journal.record_event(
        "research_proposal",
        symbol="AAPL",
        detail="hold conf=0.70 shares position: earnings volatility",
    )
    journal.record_event(
        "entry_submitted",
        symbol="AAPL",
        detail="entry=280.00 stop=278.20 tp=284.76 conf=0.83",
    )
    journal.record_event(
        "exit_failed",
        symbol="AAPL",
        detail='{"held_for_orders":"100"}',
    )
    journal.close()

    mem_path = tmp_path / "memory.json"
    store = ResearchMemoryStore(mem_path)
    added = store.sync_from_journal(db, candidate_symbols=("AAPL",))
    assert added == 1
    assert store._reflections[0].outcome == "loss"
    assert store._reflections[0].exit_reason == "broker_bracket_stop"


def test_record_session_halt(tmp_path: Path) -> None:
    store = ResearchMemoryStore(tmp_path / "memory.json")
    ref = store.record_session_halt(
        halt_reason="daily_loss_limit",
        day_pnl=-6672.0,
        equity=94_861.0,
        closed_at=datetime(2026, 6, 25, 18, 0, tzinfo=UTC),
    )
    assert ref is not None
    assert ref.symbol == "SESSION"
    assert ref.outcome == "loss"
    assert "daily_loss_limit" in ref.summary


def test_context_includes_reflections_in_prompt() -> None:
    ref = ClosedTradeReflection(
        symbol="NVDA",
        closed_at=datetime(2026, 6, 20, 15, 0, tzinfo=UTC),
        outcome="loss",
        pnl_estimate=-30.0,
        exit_reason="stop_loss",
        summary="NVDA stopped out.",
    )
    from my_trade.core.monitoring.account import AccountSnapshot

    ctx = build_research_context(
        snapshot=AccountSnapshot(equity=100_000.0),
        candidate_symbols=("NVDA", "AAPL"),
        asset_class="equities",
        session_open=True,
        as_of=datetime(2026, 6, 20, 15, 0, tzinfo=UTC),
        equity=100_000.0,
        day_pnl=-30.0,
        peak_equity=100_030.0,
        open_risk_dollars=500.0,
        recent_reflections=(ref,),
        performance=compute_performance((ref,)),
    )
    prompt = build_user_prompt(ctx, max_ideas=3)
    assert "recent_reflections" in prompt
    assert "NVDA stopped out" in prompt
    assert "recent_performance" in prompt


def test_performance_summary_win_rate() -> None:
    refs = (
        ClosedTradeReflection(
            symbol="A",
            closed_at=datetime(2026, 1, 1, tzinfo=UTC),
            outcome="win",
            pnl_estimate=10.0,
            summary="",
        ),
        ClosedTradeReflection(
            symbol="B",
            closed_at=datetime(2026, 1, 2, tzinfo=UTC),
            outcome="loss",
            pnl_estimate=-5.0,
            summary="",
        ),
    )
    perf = compute_performance(refs)
    assert perf.sample_size == 2
    assert perf.wins == 1
    assert perf.losses == 1
    assert perf.win_rate == 0.5
    assert perf.avg_pnl_estimate == 2.5


def test_note_proposals_skips_zero_confidence_avoid(tmp_path: Path) -> None:
    store = ResearchMemoryStore(tmp_path / "mem.json")
    store.note_proposals(
        (
            TradeIdea(symbol="NVDA", action=TradeAction.AVOID, confidence=0.0, thesis="noise"),
            TradeIdea(symbol="ABCD", action=TradeAction.LONG, confidence=0.7, thesis="rip"),
        )
    )
    assert store.stance_for_symbol("NVDA") is None
    assert store.stance_for_symbol("ABCD") is not None
    assert store.stance_for_symbol("ABCD").action is TradeAction.LONG


def test_clear_stance(tmp_path: Path) -> None:
    store = ResearchMemoryStore(tmp_path / "mem.json")
    store.note_proposals(
        (TradeIdea(symbol="ABCD", action=TradeAction.LONG, confidence=0.8, thesis="ok"),)
    )
    store.clear_stance()
    assert store.stance_for_symbol("ABCD") is None


def test_clear_stale_stance_preserves_same_day_veto(tmp_path: Path) -> None:
    path = tmp_path / "mem.json"
    store = ResearchMemoryStore(path)
    recorded_at = datetime(2026, 7, 11, 13, 30, tzinfo=UTC)
    store.note_proposals(
        (
            TradeIdea(
                symbol="ABCD",
                action=TradeAction.AVOID,
                confidence=0.9,
                thesis="Opening gap is fading",
            ),
        ),
        when=recorded_at,
    )

    store = ResearchMemoryStore(path)
    assert store.clear_stale_stance(date(2026, 7, 11)) == 0
    assert store.stance_for_symbol("ABCD") is not None


def test_clear_stale_stance_drops_prior_day_veto(tmp_path: Path) -> None:
    store = ResearchMemoryStore(tmp_path / "mem.json")
    store.note_proposals(
        (
            TradeIdea(
                symbol="ABCD",
                action=TradeAction.AVOID,
                confidence=0.9,
                thesis="Weak close",
            ),
        ),
        when=datetime(2026, 7, 10, 20, 0, tzinfo=UTC),
    )

    assert store.clear_stale_stance(date(2026, 7, 11)) == 1
    assert store.stance_for_symbol("ABCD") is None
