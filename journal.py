"""Persistent trade journal for dashboard and analytics."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from utils import to_eastern


@dataclass
class JournalEvent:
    """Single bot event."""

    event_type: str
    message: str
    symbol: str = ""
    metadata: Optional[Dict[str, Any]] = None
    created_at: Optional[str] = None


class TradeJournal:
    """SQLite-backed event log."""

    def __init__(self, db_path: str = "logs/journal.db") -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    symbol TEXT,
                    message TEXT NOT NULL,
                    metadata TEXT
                );
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    qty REAL,
                    entry_price REAL,
                    exit_price REAL,
                    notional REAL,
                    pnl REAL,
                    exit_reason TEXT,
                    order_id TEXT
                );
                CREATE TABLE IF NOT EXISTS universe_scans (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    eligible_count INTEGER,
                    sources TEXT,
                    symbols_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_events_created ON events(created_at);
                CREATE INDEX IF NOT EXISTS idx_trades_created ON trades(created_at);
                """
            )

    def log_event(
        self,
        event_type: str,
        message: str,
        symbol: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Append an event row."""
        ts = to_eastern().isoformat()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO events (created_at, event_type, symbol, message, metadata)
                VALUES (?, ?, ?, ?, ?)
                """,
                (ts, event_type, symbol, message, json.dumps(metadata or {})),
            )

    def log_trade_entry(
        self,
        symbol: str,
        qty: float,
        entry_price: float,
        notional: float,
        order_id: str,
        stop_price: float,
        take_profit_price: float,
    ) -> None:
        """Record a new trade entry."""
        ts = to_eastern().isoformat()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO trades (
                    created_at, symbol, side, qty, entry_price, notional, order_id
                ) VALUES (?, ?, 'buy', ?, ?, ?, ?)
                """,
                (ts, symbol, qty, entry_price, notional, order_id),
            )
        self.log_event(
            "trade_entry",
            f"ENTRY {symbol} qty={qty:.4f} @ ${entry_price:.2f}",
            symbol=symbol,
            metadata={
                "qty": qty,
                "entry_price": entry_price,
                "notional": notional,
                "order_id": order_id,
                "stop_price": stop_price,
                "take_profit_price": take_profit_price,
            },
        )

    def log_trade_exit(
        self,
        symbol: str,
        exit_reason: str,
        exit_price: Optional[float] = None,
        pnl: Optional[float] = None,
    ) -> None:
        """Update latest open trade or log exit event."""
        ts = to_eastern().isoformat()
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT id FROM trades
                WHERE symbol = ? AND exit_price IS NULL
                ORDER BY id DESC LIMIT 1
                """,
                (symbol,),
            ).fetchone()
            if row:
                conn.execute(
                    """
                    UPDATE trades SET exit_price = ?, pnl = ?, exit_reason = ?
                    WHERE id = ?
                    """,
                    (exit_price, pnl, exit_reason, row["id"]),
                )
        self.log_event(
            "trade_exit",
            f"EXIT {symbol}: {exit_reason}",
            symbol=symbol,
            metadata={"exit_reason": exit_reason, "exit_price": exit_price, "pnl": pnl},
        )

    def log_universe_scan(
        self,
        symbols: List[Dict[str, Any]],
        sources: List[str],
    ) -> None:
        """Persist universe scan snapshot."""
        ts = to_eastern().isoformat()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO universe_scans (created_at, eligible_count, sources, symbols_json)
                VALUES (?, ?, ?, ?)
                """,
                (ts, len(symbols), ",".join(sources), json.dumps(symbols)),
            )

    def get_recent_events(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM events ORDER BY id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._row_to_event(r) for r in rows]

    def get_trades(self, limit: int = 200) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM trades ORDER BY id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_latest_universe(self) -> Optional[Dict[str, Any]]:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT * FROM universe_scans ORDER BY id DESC LIMIT 1
                """
            ).fetchone()
        if not row:
            return None
        return {
            "created_at": row["created_at"],
            "eligible_count": row["eligible_count"],
            "sources": row["sources"].split(",") if row["sources"] else [],
            "symbols": json.loads(row["symbols_json"]),
        }

    def get_stats_today(self) -> Dict[str, Any]:
        """Aggregate stats for current ET day."""
        today = to_eastern().date().isoformat()
        with self._conn() as conn:
            trades = conn.execute(
                """
                SELECT * FROM trades
                WHERE created_at LIKE ? AND exit_price IS NOT NULL
                """,
                (f"{today}%",),
            ).fetchall()
            signals = conn.execute(
                """
                SELECT COUNT(*) AS c FROM events
                WHERE event_type = 'signal' AND created_at LIKE ?
                """,
                (f"{today}%",),
            ).fetchone()
            entries = conn.execute(
                """
                SELECT COUNT(*) AS c FROM events
                WHERE event_type = 'trade_entry' AND created_at LIKE ?
                """,
                (f"{today}%",),
            ).fetchone()
        closed = [dict(t) for t in trades]
        wins = sum(1 for t in closed if (t.get("pnl") or 0) > 0)
        total = len(closed)
        total_pnl = sum(t.get("pnl") or 0 for t in closed)
        return {
            "date": today,
            "closed_trades": total,
            "wins": wins,
            "losses": total - wins,
            "win_rate": (wins / total * 100) if total else 0.0,
            "total_pnl": total_pnl,
            "signals_today": signals["c"] if signals else 0,
            "entries_today": entries["c"] if entries else 0,
        }

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> Dict[str, Any]:
        meta = row["metadata"]
        return {
            "id": row["id"],
            "created_at": row["created_at"],
            "event_type": row["event_type"],
            "symbol": row["symbol"] or "",
            "message": row["message"],
            "metadata": json.loads(meta) if meta else {},
        }


def save_universe_snapshot(path: str, data: Dict[str, Any]) -> None:
    """Write latest universe JSON for dashboard file fallback."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
