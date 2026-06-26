"""One-off audit for 2026-06-25 session."""
import sqlite3
from pathlib import Path

db = Path(__file__).resolve().parents[1] / "logs" / "journal.db"
conn = sqlite3.connect(db)
conn.row_factory = sqlite3.Row
day = "2026-06-25"

print("=== TRADES ===")
for r in conn.execute(
    "SELECT ts, kind, symbol, equity, day_pnl, detail FROM events "
    "WHERE ts >= ? AND kind IN ('entry_submitted','exit_submitted') ORDER BY ts",
    (day,),
):
    print(f"{r['ts'][:19]} | {r['kind']:16} | {r['symbol']:6} | eq={r['equity']} | {(r['detail'] or '')[:100]}")

print("\n=== HALTS / ERRORS ===")
for r in conn.execute(
    "SELECT ts, kind, equity, day_pnl, detail FROM events "
    "WHERE ts >= ? AND kind IN ('halt','error') ORDER BY ts",
    (day,),
):
    print(f"{r['ts'][:19]} | {r['kind']} | eq={r['equity']} pnl={r['day_pnl']} | {(r['detail'] or '')[:120]}")

print("\n=== RESEARCH PROPOSALS (first 20) ===")
for r in conn.execute(
    "SELECT ts, symbol, detail FROM events "
    "WHERE ts >= ? AND kind='research_proposal' ORDER BY ts LIMIT 20",
    (day,),
):
    print(f"{r['ts'][:19]} | {r['symbol']:6} | {(r['detail'] or '')[:140]}")

print("\n=== ENTRY REJECTIONS (top reasons) ===")
from collections import Counter
c = Counter()
for r in conn.execute(
    "SELECT detail FROM events WHERE ts >= ? AND kind='entry_rejected'",
    (day,),
):
    reason = (r["detail"] or "").split(":")[0][:60]
    c[reason] += 1
for k, v in c.most_common(10):
    print(v, k)

print("\n=== AAPL RESEARCH PROPOSALS ===")
for r in conn.execute(
    "SELECT ts, detail FROM events WHERE ts >= ? AND kind='research_proposal' AND symbol='AAPL' ORDER BY ts LIMIT 12",
    (day,),
):
    print(f"{r['ts'][:19]} | {(r['detail'] or '')[:160]}")

print("\n=== EXITS TODAY ===")
for r in conn.execute(
    "SELECT ts, kind, symbol, detail FROM events WHERE ts >= ? AND kind IN ('exit_submitted','exit_failed') ORDER BY ts LIMIT 15",
    (day,),
):
    print(dict(r))

print("\n=== RESEARCH BY ACTION ===")
for r in conn.execute(
    "SELECT detail FROM events WHERE ts >= ? AND kind='research_proposal'",
    (day,),
):
    d = r["detail"] or ""
    if "avoid" in d.lower():
        tag = "avoid"
    elif "long" in d.lower():
        tag = "long"
    elif "hold" in d.lower():
        tag = "hold"
    else:
        tag = "other"
    from collections import Counter
    break
c2 = Counter()
for r in conn.execute(
    "SELECT detail FROM events WHERE ts >= ? AND kind='research_proposal'",
    (day,),
):
    d = (r["detail"] or "").lower()
    if "[premium]" in d or "avoid" in d:
        c2["avoid/hold-ish"] += 1
    elif "long" in d:
        c2["long"] += 1
    elif "hold" in d:
        c2["hold"] += 1
for k, v in c2.most_common():
    print(v, k)

print("\n=== FIRST HALT ===")
r = conn.execute(
    "SELECT ts, equity, day_pnl FROM events WHERE ts >= ? AND kind='halt' ORDER BY ts LIMIT 1",
    (day,),
).fetchone()
print(dict(r) if r else "none")
rows = conn.execute(
    "SELECT ts, equity, day_pnl, kind FROM events "
    "WHERE ts >= ? AND equity IS NOT NULL ORDER BY equity ASC LIMIT 5",
    (day,),
).fetchall()
print("Lowest equity snapshots:")
for r in rows:
    print(dict(r))
rows2 = conn.execute(
    "SELECT ts, equity, day_pnl FROM events "
    "WHERE ts >= ? AND kind='halt' ORDER BY ts",
    (day,),
).fetchall()
print("At halt:", [dict(r) for r in rows2])
