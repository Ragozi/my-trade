"""Quick today report from journal."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from my_trade.config import load_settings
from my_trade.core.monitoring import DailyStateStore
from my_trade.observability.journal import Journal
from my_trade.research.history import all_closed_trades_from_events


def main() -> None:
    settings = load_settings()
    today = date.today().isoformat()
    journal = Journal(settings.runtime.journal_db)
    events = list(journal.fetch_recent(8000))
    events.reverse()
    journal.close()
    today_events = [e for e in events if e.ts.startswith(today)]

    print(f"TODAY {today}")
    print("=== CLOSED TRADES ===")
    for t in all_closed_trades_from_events(today_events):
        thesis = (t.thesis_at_entry or "")[:75]
        print(
            f"  {t.symbol:5} exit {t.exit_ts[11:19]} "
            f"{t.exit_reason:22} day_pnl_at_exit={t.day_pnl_at_exit} | {thesis}"
        )

    print("\n=== ENTRIES ===")
    for e in today_events:
        if e.kind == "entry_submitted":
            print(f"  {e.ts[11:19]} {e.symbol} {e.detail[:85]}")

    print("\n=== REFLECTIONS ===")
    for e in today_events:
        if e.kind == "research_reflection":
            print(f"  {e.ts[11:19]} {e.symbol or 'SESSION'}: {e.detail[:140]}")

    hb = [e for e in today_events if e.kind == "heartbeat"]
    if hb:
        last = hb[-1]
        print(f"\nLast heartbeat: equity={last.equity} day_pnl={last.day_pnl}")

    ds = DailyStateStore(settings.runtime.daily_state_file).load()
    if ds:
        print(f"Peak today: ${ds.peak_equity:.2f} (start ${ds.start_of_day_equity:.2f})")
        print(f"Entries today: {ds.entries_today}")


if __name__ == "__main__":
    main()
