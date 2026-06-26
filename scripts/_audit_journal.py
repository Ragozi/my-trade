"""One-off journal audit — last 48h."""
from __future__ import annotations

import sqlite3
from collections import Counter
from pathlib import Path

db = Path(__file__).resolve().parents[1] / "logs" / "journal.db"
conn = sqlite3.connect(str(db))
rows = conn.execute(
    "SELECT ts, kind, symbol, detail, equity, day_pnl FROM events "
    "WHERE ts >= '2026-06-21' ORDER BY id"
).fetchall()
conn.close()

print("TOTAL_EVENTS", len(rows))
print("BY_KIND:")
for k, v in Counter(r[1] for r in rows).most_common():
    print(f"  {k}: {v}")

interesting = {
    "entry_submitted", "exit_submitted", "entry_rejected", "exit_failed",
    "halt", "error", "research_proposal", "research_skipped", "research_reflection",
    "daily_rollover",
}
print("\n--- KEY EVENTS ---")
for r in rows:
    if r[1] in interesting:
        ts, kind, sym, detail, eq, pnl = r
        print(f"{ts[:19]}Z | {kind:22} | {sym or '-':6} | eq={eq} | {(detail or '')[:85]}")
