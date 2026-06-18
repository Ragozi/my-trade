"""Tests for the SQLite trade journal."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from my_trade.core.monitoring import ActionKind, CycleAction, CycleResult, HaltReason
from my_trade.observability import Journal

NOW = datetime(2026, 6, 18, 14, 7, tzinfo=UTC)


def _result(*actions: CycleAction, halted: bool = False) -> CycleResult:
    return CycleResult(
        timestamp=NOW,
        equity=12_000.0,
        day_pnl=-50.0,
        peak_equity=12_300.0,
        open_positions=0,
        halted=halted,
        halt_reason=HaltReason.DAILY_LOSS_LIMIT if halted else None,
        actions=actions,
    )


class TestJournal:
    def test_record_and_fetch(self, tmp_path: Path) -> None:
        with Journal(tmp_path / "j.db") as journal:
            journal.record_event("entry_submitted", symbol="BTC/USD", detail="ok", equity=12_000.0)
            events = journal.fetch_all()
        assert len(events) == 1
        assert events[0].kind == "entry_submitted"
        assert events[0].symbol == "BTC/USD"
        assert events[0].equity == 12_000.0

    def test_creates_nested_directory(self, tmp_path: Path) -> None:
        path = tmp_path / "nested" / "logs" / "journal.db"
        with Journal(path) as journal:
            journal.record_event("halt", detail="circuit_breaker")
        assert path.exists()

    def test_log_cycle_only_persists_material_actions(self, tmp_path: Path) -> None:
        result = _result(
            CycleAction(ActionKind.ENTRY_SUBMITTED, "BTC/USD", status="submitted"),
            CycleAction(ActionKind.NO_SIGNAL, "BTC/USD", "weak"),
            CycleAction(ActionKind.SKIP_MAX_ENTRIES, "BTC/USD"),
            CycleAction(ActionKind.HALT, detail="daily_loss_limit"),
        )
        with Journal(tmp_path / "j.db") as journal:
            written = journal.log_cycle(result)
            kinds = [e.kind for e in journal.fetch_all()]
        assert written == 2
        assert kinds == ["entry_submitted", "halt"]

    def test_log_cycle_carries_equity_and_pnl(self, tmp_path: Path) -> None:
        result = _result(CycleAction(ActionKind.EXIT_SUBMITTED, "BTC/USD", "time_stop"))
        with Journal(tmp_path / "j.db") as journal:
            journal.log_cycle(result)
            event = journal.fetch_all()[0]
        assert event.equity == 12_000.0
        assert event.day_pnl == -50.0
        assert event.detail == "time_stop"

    def test_record_rollover(self, tmp_path: Path) -> None:
        with Journal(tmp_path / "j.db") as journal:
            journal.record_rollover("2026-06-18", 12_000.0, ts=NOW)
            events = journal.fetch_all()
        assert events[0].kind == "daily_rollover"
        assert "2026-06-18" in events[0].detail
