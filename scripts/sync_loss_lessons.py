"""Backfill research memory from journal (incl. broker-side closes)."""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from my_trade.config import load_settings  # noqa: E402
from my_trade.research.factory import build_research_memory  # noqa: E402


def _maybe_sync_session_halt(memory, journal_path: Path) -> None:
    import sqlite3
    from datetime import datetime

    if any(r.symbol == "SESSION" for r in memory._reflections):
        return
    conn = sqlite3.connect(journal_path)
    row = conn.execute(
        "SELECT ts, day_pnl, equity FROM events "
        "WHERE kind='halt' AND detail='daily_loss_limit' AND day_pnl IS NOT NULL "
        "ORDER BY ts DESC LIMIT 1"
    ).fetchone()
    conn.close()
    if row is None:
        return
    ts, day_pnl, equity = row
    memory.record_session_halt(
        halt_reason="daily_loss_limit",
        day_pnl=float(day_pnl),
        equity=float(equity or 0),
        closed_at=datetime.fromisoformat(ts),
    )


def main() -> None:
    settings = load_settings()
    memory = build_research_memory(settings)
    if memory is None:
        print("Research memory disabled (ENABLE_RESEARCH=false)")
        return
    journal = Path(settings.runtime.log_dir) / "journal.db"
    added = memory.sync_from_journal(
        journal,
        candidate_symbols=settings.symbols,
        limit_events=2000,
    )
    _maybe_sync_session_halt(memory, journal)
    print(f"Synced {added} new reflection(s) from {journal}")
    print(f"Total reflections in memory: {len(memory._reflections)}")


if __name__ == "__main__":
    main()
