"""Quick end-of-day summary from journal + Alpaca."""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter
from datetime import date
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from my_trade.api.bot_manager import get_bot_status
from my_trade.config import load_settings
from my_trade.core.monitoring.alpaca_account import AlpacaAccountProvider
from my_trade.core.monitoring.state import resolve_risk_equity
from my_trade.core.monitoring.store import DailyStateStore


def main() -> None:
    settings = load_settings()
    today = date.today().isoformat()
    print(f"=== TODAY {today} ===")
    print("Bot:", get_bot_status(settings.runtime.log_dir))

    ds = DailyStateStore(settings.runtime.daily_state_file).load()
    if ds:
        print(
            "Daily state:",
            json.dumps(
                {
                    "trading_day": ds.trading_day.isoformat(),
                    "start_sod": ds.start_of_day_equity,
                    "peak": ds.peak_equity,
                    "entries_today": ds.entries_today,
                    "broker_sod": ds.broker_sod_equity,
                },
                indent=2,
            ),
        )

    conn = sqlite3.connect(settings.runtime.journal_db)
    rows = conn.execute(
        "SELECT ts, kind, symbol, detail, equity, day_pnl FROM events "
        "WHERE ts LIKE ? ORDER BY id",
        (f"{today}%",),
    ).fetchall()
    conn.close()

    kinds = Counter(r[1] for r in rows)
    print("Journal events:", dict(kinds))
    print("Total events:", len(rows))

    for label, kind in [
        ("Entries", "entry_submitted"),
        ("Exits", "exit_submitted"),
        ("Exit fails", "exit_failed"),
    ]:
        items = [r for r in rows if r[1] == kind]
        print(f"{label}: {len(items)}")
        for r in items:
            print(f"  {r[0][11:19]} {r[2]} {(r[3] or '')[:100]}")

    halts = [r for r in rows if r[1] == "halt"]
    print("Halts:", len(halts), "reasons:", dict(Counter(r[3] for r in halts)))
    print("Research proposals:", sum(1 for r in rows if r[1] == "research_proposal"))
    print("Research skipped:", sum(1 for r in rows if r[1] == "research_skipped"))
    print(
        "Top entry rejects:",
        Counter((r[3] or "")[:70] for r in rows if r[1] == "entry_rejected").most_common(8),
    )

    snap = AlpacaAccountProvider(
        settings.alpaca.api_key,
        settings.alpaca.api_secret,
        paper=settings.alpaca.paper_trading,
    ).get_snapshot()
    tc = settings.risk.trading_capital
    if ds and tc > 0:
        eq, pnl, sod = resolve_risk_equity(snap.equity, ds, trading_capital=tc)
    else:
        eq, pnl, sod = snap.equity, snap.equity - (ds.start_of_day_equity if ds else snap.equity), snap.equity
    print(f"Virtual: equity=${eq:,.2f} day_pnl=${pnl:+,.2f} sod=${sod:,.2f}")
    print(f"Broker:  equity=${snap.equity:,.2f} positions={len(snap.positions)}")
    for p in snap.positions:
        print(
            f"  {p.symbol} qty={p.qty} entry=${p.avg_entry_price:.2f} "
            f"upl=${p.unrealized_pl:+.2f} mkt=${p.market_value:,.2f}"
        )


if __name__ == "__main__":
    main()
