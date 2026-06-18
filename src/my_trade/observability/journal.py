"""Lightweight SQLite trade journal.

Records material events (entries, exits, halts, errors, daily rollover) to a
single ``events`` table for later review/backtesting. Deliberately minimal: no
ORM, no migrations, no Slack — just an append-only audit trail.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from my_trade.core.monitoring import CycleResult

# Cycle actions worth persisting (skip routine no-signal / skip noise).
_MATERIAL_ACTIONS = frozenset(
    {
        "entry_submitted",
        "entry_rejected",
        "exit_submitted",
        "exit_failed",
        "halt",
        "error",
    }
)


@dataclass(frozen=True)
class JournalEvent:
    ts: str
    kind: str
    symbol: str
    detail: str
    equity: float | None
    day_pnl: float | None


class Journal:
    """Append-only SQLite event log. Safe to construct repeatedly (idempotent)."""

    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)
        if self._path.parent and not self._path.parent.exists():
            self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path))
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                ts        TEXT NOT NULL,
                kind      TEXT NOT NULL,
                symbol    TEXT NOT NULL DEFAULT '',
                detail    TEXT NOT NULL DEFAULT '',
                equity    REAL,
                day_pnl   REAL
            )
            """
        )
        self._conn.commit()

    def record_event(
        self,
        kind: str,
        *,
        symbol: str = "",
        detail: str = "",
        equity: float | None = None,
        day_pnl: float | None = None,
        ts: datetime | None = None,
    ) -> None:
        timestamp = (ts or datetime.now(UTC)).isoformat()
        self._conn.execute(
            "INSERT INTO events (ts, kind, symbol, detail, equity, day_pnl) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (timestamp, kind, symbol, detail, equity, day_pnl),
        )
        self._conn.commit()

    def record_rollover(self, trading_day: str, equity: float, ts: datetime | None = None) -> None:
        self.record_event(
            "daily_rollover", detail=f"new trading day {trading_day}", equity=equity, ts=ts
        )

    def log_cycle(self, result: CycleResult) -> int:
        """Persist material actions from a cycle; returns the number written."""
        written = 0
        for action in result.actions:
            if action.kind.value not in _MATERIAL_ACTIONS:
                continue
            self.record_event(
                action.kind.value,
                symbol=action.symbol,
                detail=action.detail or action.status,
                equity=result.equity,
                day_pnl=result.day_pnl,
                ts=result.timestamp,
            )
            written += 1
        return written

    def fetch_all(self) -> Sequence[JournalEvent]:
        rows = self._conn.execute(
            "SELECT ts, kind, symbol, detail, equity, day_pnl FROM events ORDER BY id"
        ).fetchall()
        return [
            JournalEvent(
                ts=r[0], kind=r[1], symbol=r[2], detail=r[3], equity=r[4], day_pnl=r[5]
            )
            for r in rows
        ]

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> Journal:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
