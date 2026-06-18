"""FastAPI dashboard server — run: python -m dashboard.server"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from broker import AlpacaBroker
from config import get_settings
from journal import TradeJournal

app = FastAPI(title="My-Trade Dashboard", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = Path(__file__).parent / "static"
_settings = None
_journal: Optional[TradeJournal] = None


def _get_journal() -> TradeJournal:
    global _journal
    if _journal is None:
        s = get_settings()
        _journal = TradeJournal(s.journal_db)
    return _journal


def _load_universe_file() -> Optional[Dict[str, Any]]:
    path = Path("logs/last_universe.json")
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def _load_daily_state() -> Dict[str, Any]:
    path = Path(get_settings().daily_state_file)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


@app.get("/api/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/api/config")
def api_config() -> Dict[str, Any]:
    s = get_settings()
    return {
        "crypto_mode": s.crypto_mode,
        "symbols": s.symbols,
        "notional_per_trade": s.notional_per_trade,
        "paper_trading": s.paper_trading,
        "stop_loss_pct": s.stop_loss_pct,
        "take_profit_pct": s.take_profit_pct,
        "max_hold_minutes": s.max_hold_minutes,
        "scan_interval_seconds": s.scan_interval_seconds,
        "require_15m_uptrend": s.require_15m_uptrend,
        "require_volume_spike": s.require_volume_spike,
        "crypto_mode": s.crypto_mode,
    }


@app.get("/api/account")
def api_account() -> Dict[str, Any]:
    """Live account from Alpaca (optional)."""
    try:
        s = get_settings()
        if not s.api_key:
            return {"error": "API keys not configured"}
        broker = AlpacaBroker(s)
        acct = broker.get_account()
        positions = broker.get_open_positions()
        pnl = broker.get_today_realized_pnl()
        return {
            "equity": acct["equity"],
            "buying_power": acct["buying_power"],
            "cash": acct["cash"],
            "daily_pnl": pnl,
            "positions": positions,
            "market_open": broker.is_market_open(),
        }
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/api/stats")
def api_stats() -> Dict[str, Any]:
    journal = _get_journal()
    today = journal.get_stats_today()
    daily = _load_daily_state()
    return {
        "today": today,
        "daily_state": daily,
    }


@app.get("/api/events")
def api_events(limit: int = 150) -> List[Dict[str, Any]]:
    return _get_journal().get_recent_events(limit)


@app.get("/api/trades")
def api_trades(limit: int = 100) -> List[Dict[str, Any]]:
    return _get_journal().get_trades(limit)


@app.get("/api/universe")
def api_universe() -> Dict[str, Any]:
    latest = _get_journal().get_latest_universe()
    file_data = _load_universe_file()
    return {"journal": latest, "file": file_data}


@app.get("/api/equity-curves")
def api_equity_curves() -> List[Dict[str, Any]]:
    """List available backtest equity curve files."""
    log_dir = Path(get_settings().log_dir)
    curves = []
    for p in sorted(log_dir.glob("backtest_*.csv"), reverse=True)[:20]:
        curves.append({"name": p.name, "path": str(p), "symbol": p.stem.split("_")[1] if "_" in p.stem else ""})
    return curves


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def main() -> None:
    import uvicorn

    s = get_settings()
    print(f"\n  My-Trade Dashboard → http://{s.dashboard_host}:{s.dashboard_port}\n")
    uvicorn.run(
        "dashboard.server:app",
        host=s.dashboard_host,
        port=s.dashboard_port,
        reload=False,
    )


if __name__ == "__main__":
    main()
