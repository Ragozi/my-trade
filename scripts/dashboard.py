"""Simple local monitoring dashboard for the paper trading loop.

Reads the SQLite journal (logs/journal.db) and shows current equity, day P&L,
and recent activity. Read-only — it never touches Alpaca or places orders.

Run with:  streamlit run scripts/dashboard.py   (or: poe dashboard)
Install deps once:  pip install -e .[dashboard]
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running without an editable install: put ``src`` on the path.
_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

try:
    import streamlit as st  # noqa: E402
except ImportError:  # pragma: no cover - dashboard is optional
    raise SystemExit(
        "Streamlit is not installed. Install the dashboard extra:\n"
        "    pip install -e .[dashboard]"
    ) from None

import pandas as pd  # noqa: E402

from my_trade.config import load_settings  # noqa: E402
from my_trade.observability import Journal  # noqa: E402


def journal_path() -> str:
    try:
        return load_settings().runtime.journal_db
    except Exception:
        return "logs/journal.db"


def render() -> None:
    st.set_page_config(page_title="My-Trade Paper Monitor", layout="wide")
    st.title("My-Trade — Paper Trading Monitor")

    path = journal_path()
    st.caption(f"Journal: `{path}` (read-only)")

    if not Path(path).exists():
        st.warning(
            "No journal yet. Start the paper loop first:\n\n"
            "`python -m scripts.paper_trade`  (or `poe paper`)"
        )
        return

    journal = Journal(path)
    try:
        latest = journal.latest_equity()
        events = journal.fetch_recent(300)
    finally:
        journal.close()

    col1, col2, col3, col4 = st.columns(4)
    if latest is not None:
        equity, day_pnl = latest
        col1.metric("Equity", f"${equity:,.2f}")
        col2.metric("Day P&L", f"${day_pnl:,.2f}")
    else:
        col1.metric("Equity", "n/a")
        col2.metric("Day P&L", "n/a")

    entries = sum(1 for e in events if e.kind == "entry_submitted")
    exits = sum(1 for e in events if e.kind == "exit_submitted")
    halts = sum(1 for e in events if e.kind == "halt")
    col3.metric("Entries / Exits", f"{entries} / {exits}")
    col4.metric("Halts (recent)", f"{halts}")

    st.subheader("Recent activity")
    trade_events = [e for e in events if e.kind != "heartbeat"]
    if trade_events:
        frame = pd.DataFrame(
            [
                {
                    "time": e.ts,
                    "event": e.kind,
                    "symbol": e.symbol,
                    "detail": e.detail,
                    "equity": e.equity,
                    "day_pnl": e.day_pnl,
                }
                for e in trade_events
            ]
        )
        st.dataframe(frame, use_container_width=True, hide_index=True)
    else:
        st.info("No trade events recorded yet (entries/exits/halts will appear here).")

    st.caption("Refresh the page to update. Heartbeat rows are hidden from the table.")


render()
