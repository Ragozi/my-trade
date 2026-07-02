"""Tests for structured trade knowledge store."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

from my_trade.observability.journal import Journal
from my_trade.research.knowledge import TradeKnowledgeStore
from my_trade.research.memory import ResearchMemoryStore
from my_trade.research.models import TradeAction, TradeIdea
from my_trade.research.prompts import build_user_prompt
from my_trade.research.context import build_research_context
from my_trade.core.monitoring.account import AccountSnapshot


def _journal_with_round_trip(tmp_path: Path) -> Path:
    db = tmp_path / "journal.db"
    journal = Journal(db)
    journal.record_event(
        "research_proposal",
        symbol="AAPL",
        detail="[openai] long conf=0.72 shares swing: Pullback above 50dma",
    )
    journal.record_event(
        "entry_submitted",
        symbol="AAPL",
        detail="entry @ 190.50 stop=188.00",
        equity=15000.0,
        day_pnl=0.0,
    )
    journal.record_event(
        "exit_submitted",
        symbol="AAPL",
        detail="time_stop",
        equity=15020.0,
        day_pnl=20.0,
    )
    journal.close()
    return db


def test_ingest_journal_entry_and_exit(tmp_path: Path) -> None:
    kb_path = tmp_path / "knowledge.json"
    store = TradeKnowledgeStore(str(kb_path))
    db = _journal_with_round_trip(tmp_path)

    added = store.sync_from_journal(str(db))
    assert added >= 2
    assert store.record_count >= 2

    rows = store.recent_for_prompt(symbols=["AAPL"], limit=10)
    assert any(r["event"] == "entry" for r in rows)
    assert any(r["event"] == "exit" for r in rows)
    exit_row = next(r for r in rows if r["event"] == "exit")
    assert exit_row["what"]
    assert exit_row["how"]
    assert exit_row["why"]


def test_sync_is_idempotent(tmp_path: Path) -> None:
    kb_path = tmp_path / "knowledge.json"
    store = TradeKnowledgeStore(str(kb_path))
    db = _journal_with_round_trip(tmp_path)

    first = store.sync_from_journal(str(db))
    second = store.sync_from_journal(str(db))
    assert first >= 2
    assert second == 0
    assert store.record_count >= 2


def test_finalize_trading_day_once(tmp_path: Path) -> None:
    kb_path = tmp_path / "knowledge.json"
    store = TradeKnowledgeStore(str(kb_path))
    db = _journal_with_round_trip(tmp_path)
    store.sync_from_journal(str(db))

    day = date(2026, 6, 30)
    summary = store.finalize_trading_day(day, equity=15020.0, day_pnl=20.0)
    assert summary is not None
    assert summary.day_pnl == 20.0

    again = store.finalize_trading_day(day, equity=15020.0, day_pnl=20.0)
    assert again is None

    raw = json.loads(kb_path.read_text(encoding="utf-8"))
    assert len(raw["daily_summaries"]) == 1


def test_record_from_reflection(tmp_path: Path) -> None:
    mem_path = tmp_path / "memory.json"
    kb_path = tmp_path / "knowledge.json"
    memory = ResearchMemoryStore(mem_path)
    memory.note_proposals(
        (
            TradeIdea(
                symbol="NVDA",
                action=TradeAction.LONG,
                confidence=0.8,
                thesis="AI demand tailwind",
            ),
        )
    )
    reflection = memory.record_close(
        symbol="NVDA",
        exit_reason="time_stop",
        entry_price=120.0,
        qty=10.0,
        unrealized_pl=15.0,
        closed_at=datetime(2026, 6, 30, 20, 0, tzinfo=UTC),
    )

    store = TradeKnowledgeStore(str(kb_path))
    rec = store.record_from_reflection(reflection)
    assert rec is not None
    assert rec.outcome == "win"
    assert "AI demand" in rec.why_it_happened


def test_api_payload_filters(tmp_path: Path) -> None:
    kb_path = tmp_path / "knowledge.json"
    store = TradeKnowledgeStore(str(kb_path))
    db = _journal_with_round_trip(tmp_path)
    store.sync_from_journal(str(db))

    payload = store.api_payload(limit=10, symbol="AAPL", event_kind="exit")
    assert payload["record_count"] >= 1
    assert "stats" in payload
    assert payload["stats"]["exits"] >= 1
    assert all(r["symbol"] == "AAPL" for r in payload["records"])
    assert all(r["event_kind"] == "exit" for r in payload["records"])


def test_api_payload_shape(tmp_path: Path) -> None:
    kb_path = tmp_path / "knowledge.json"
    store = TradeKnowledgeStore(str(kb_path))
    payload = store.api_payload()
    assert payload["file"] == str(kb_path)
    assert payload["record_count"] == 0
    assert payload["records"] == []
    assert payload["stats"]["entries"] == 0


def test_prompt_includes_trade_knowledge_log() -> None:
    snapshot = AccountSnapshot(equity=15000.0, cash=15000.0, positions=())
    context = build_research_context(
        snapshot=snapshot,
        candidate_symbols=("AAPL",),
        asset_class="equities",
        session_open=True,
        as_of=datetime(2026, 6, 30, 15, 0, tzinfo=UTC),
        equity=15000.0,
        day_pnl=10.0,
        peak_equity=15100.0,
        trade_knowledge=(
            {
                "symbol": "AAPL",
                "event": "exit",
                "outcome": "win",
                "what": "AAPL closed green on time_stop",
                "how": "Python strategy time_stop fired",
                "why": "Pullback thesis",
                "lessons": [],
            },
        ),
    )
    prompt = build_user_prompt(context, max_ideas=3)
    assert "trade_knowledge_log" in prompt
    assert "time_stop" in prompt
