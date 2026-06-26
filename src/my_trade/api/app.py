"""FastAPI operator API for the Lovable My-Trade console.

Thin I/O boundary: reads journal + daily state, proxies Alpaca account snapshots,
starts/stops the paper runner subprocess, and applies whitelisted .env patches.
The deterministic trading logic stays in the core — this layer only orchestrates
and exposes state.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from my_trade.api.bot_manager import (
    get_bot_status,
    start_bot,
    stop_bot,
    tail_log,
)
from my_trade.api.env_patch import apply_env_patch, patch_to_env_updates, resolve_symbol_key
from my_trade.api.serializers import (
    event_to_json,
    settings_to_config,
    stats_from_events,
    watchlist_to_json,
)
from my_trade.config import load_settings
from my_trade.core.market_calendar import make_session_guard
from my_trade.core.monitoring import DailyStateStore
from my_trade.core.monitoring.alpaca_account import AlpacaAccountProvider
from my_trade.core.screening import Screener, StaticUniverseSource
from my_trade.data.alpaca_data import AlpacaDataProvider
from my_trade.data.alpaca_movers import AlpacaMoversUniverse
from my_trade.data.stock_data import StockHistoricalDataProvider
from my_trade.observability import Journal


# Lazy import for one-shot actions to avoid circular imports at module load.
def _paper_helpers() -> Any:
    from scripts import paper_trade as pt

    return pt


def create_app() -> FastAPI:
    app = FastAPI(title="My-Trade API", version="1.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        settings = load_settings()
        bot = get_bot_status(settings.runtime.log_dir)
        return {
            "status": "ok",
            "bot_running": bot.running,
            "asset_class": settings.asset_class,
            "paper_trading": settings.alpaca.paper_trading,
        }

    @app.get("/api/status")
    def status() -> dict[str, Any]:
        settings = load_settings()
        bot = get_bot_status(settings.runtime.log_dir)
        session_open = make_session_guard(settings.asset_class)(datetime.now(UTC))
        rc = settings.research
        research_active = rc.enabled and rc.any_tier_enabled and (
            not rc.equities_only or settings.is_equities
        )
        wh = rc.workhorse
        return {
            "bot": {
                "running": bot.running,
                "pid": bot.pid,
                "started_at": bot.started_at,
                "last_cycle_at": bot.last_cycle_at,
                "cycles_today": bot.cycles_today,
            },
            "session": {"open": session_open, "asset_class": settings.asset_class},
            "halted": bot.halted,
            "halt_reason": bot.halt_reason,
            "research": {
                "enabled": rc.enabled,
                "active": research_active,
                "require_approval": rc.require_approval_for_entry,
                "tier_mode": rc.tier_mode,
                "claude_enabled": rc.claude_enabled,
                "claude_model": rc.model if rc.claude_enabled else None,
                "workhorse_provider": wh.provider if wh.is_active else None,
                "workhorse_model": (
                    wh.openai_model
                    if wh.provider == "openai"
                    else wh.xai_model
                    if wh.provider == "xai"
                    else None
                ),
                "premium_provider": (
                    rc.premium.provider if rc.premium_active else None
                ),
                "premium_model": (
                    rc.premium.openai_model
                    if rc.premium_active and rc.premium.provider == "openai"
                    else rc.premium.xai_model
                    if rc.premium_active and rc.premium.provider == "xai"
                    else None
                ),
                "model": rc.model if rc.claude_enabled else None,
            },
        }

    @app.get("/api/account")
    def account() -> dict[str, Any]:
        settings = load_settings()
        store = DailyStateStore(settings.runtime.daily_state_file)
        daily = store.load()
        peak = daily.peak_equity if daily else 0.0
        start_eq = daily.start_of_day_equity if daily else 0.0
        try:
            settings.validate_for_trading()
            snap = AlpacaAccountProvider(
                settings.alpaca.api_key,
                settings.alpaca.api_secret,
                paper=settings.alpaca.paper_trading,
            ).get_snapshot()
        except Exception as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        tc = settings.risk.trading_capital
        risk_equity = snap.equity
        day_pnl = snap.equity - start_eq if daily else 0.0
        if daily and tc > 0:
            from my_trade.core.monitoring.state import resolve_risk_equity

            risk_equity, day_pnl, start_eq = resolve_risk_equity(
                snap.equity, daily, trading_capital=tc
            )
            if daily.broker_sod_equity <= 0:
                risk_equity, day_pnl, start_eq = tc, 0.0, tc
        elif daily:
            day_pnl = snap.equity - start_eq
        if daily:
            peak = max(peak, risk_equity if tc > 0 else snap.equity)
        positions = [
            {
                "symbol": p.symbol,
                "qty": p.qty,
                "avg_entry_price": p.avg_entry_price,
                "market_value": p.market_value,
                "unrealized_pl": p.unrealized_pl,
            }
            for p in snap.positions
        ]
        return {
            "equity": risk_equity if tc > 0 else snap.equity,
            "broker_equity": snap.equity,
            "trading_capital": tc if tc > 0 else None,
            "cash": snap.cash,
            "buying_power": snap.cash,
            "day_pnl": day_pnl,
            "peak_equity": peak,
            "open_positions": len(positions),
            "positions": positions,
        }

    @app.get("/api/config")
    def config() -> dict[str, Any]:
        return settings_to_config(load_settings())

    class SettingsPatch(BaseModel):
        model_config = {"extra": "allow"}

    @app.patch("/api/settings")
    def patch_settings(body: SettingsPatch) -> dict[str, Any]:
        settings = load_settings()
        patch = body.model_dump(exclude_unset=True)
        updates = patch_to_env_updates(patch)
        asset_class = str(patch.get("asset_class", settings.asset_class))
        updates = resolve_symbol_key(updates, asset_class)
        if not updates:
            return {
                "ok": False,
                "requires_restart": False,
                "message": "No recognized settings fields in patch",
            }
        env_path = Path(".env")
        if not env_path.exists():
            raise HTTPException(status_code=400, detail=".env file not found")
        apply_env_patch(env_path, updates)
        return {
            "ok": True,
            "requires_restart": True,
            "message": f"Updated {len(updates)} setting(s). Restart the bot to apply.",
        }

    @app.get("/api/events")
    def events(
        limit: int = Query(200, ge=1, le=2000),
        kind: str | None = None,
        symbol: str | None = None,
    ) -> list[dict[str, Any]]:
        settings = load_settings()
        journal = Journal(settings.runtime.journal_db)
        try:
            rows = journal.fetch_recent(limit)
        finally:
            journal.close()
        out = [event_to_json(e) for e in rows]
        if kind:
            out = [e for e in out if e["kind"] == kind]
        if symbol:
            sym = symbol.upper()
            out = [e for e in out if (e.get("symbol") or "").upper() == sym]
        return out

    @app.get("/api/stats")
    def stats() -> dict[str, Any]:
        settings = load_settings()
        journal = Journal(settings.runtime.journal_db)
        try:
            events = list(journal.fetch_recent(500))
            latest = journal.latest_equity()
        finally:
            journal.close()
        daily = DailyStateStore(settings.runtime.daily_state_file).load()
        return stats_from_events(events, daily, latest)

    @app.get("/api/watchlist")
    def watchlist() -> dict[str, Any]:
        settings = load_settings()
        sc = settings.screener
        if not sc.enabled:
            return watchlist_to_json(
                list(settings.symbols),
                [],
                refreshed_at=None,
                universe_source="static_config",
            )
        if settings.is_equities and sc.use_movers:
            universe: Any = AlpacaMoversUniverse(
                settings.alpaca.api_key,
                settings.alpaca.api_secret,
                source=sc.movers_source,
                top=sc.movers_top,
                min_volume=sc.movers_min_volume,
            )
            source = f"movers:{sc.movers_source}"
        else:
            static = settings.symbols if settings.is_equities else sc.universe
            universe = StaticUniverseSource(static)
            source = "static"
        data: Any = (
            StockHistoricalDataProvider.from_settings(settings)
            if settings.is_equities
            else AlpacaDataProvider.from_settings(settings)
        )
        screener = Screener(
            data=data,
            universe=universe,
            criteria=sc.to_criteria(),
            timeframe=sc.timeframe,
            bar_limit=sc.bar_limit,
            atr_period=sc.atr_period,
            lookback=sc.lookback,
            refresh_seconds=sc.refresh_seconds,
        )
        ranked = screener.screen()
        return watchlist_to_json(
            [c.symbol for c in ranked],
            ranked,
            refreshed_at=datetime.now(UTC),
            universe_source=source,
        )

    @app.get("/api/logs")
    def logs(tail: int = Query(100, ge=1, le=500)) -> dict[str, list[str]]:
        settings = load_settings()
        return {"lines": tail_log(settings.runtime.log_dir, tail)}

    @app.post("/api/bot/health-check")
    def bot_health_check() -> dict[str, Any]:
        pt = _paper_helpers()
        settings = load_settings()
        try:
            settings.validate_for_trading()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        pt.refuse_if_live(settings)
        providers = pt.build_providers(settings)
        ok = pt.run_health_checks(settings, providers)
        return {
            "ok": ok,
            "message": "Health checks passed" if ok else "Health checks failed",
            "checks": {"account": ok, "data": ok, "execution": ok},
        }

    @app.post("/api/bot/once")
    def bot_once() -> dict[str, Any]:
        pt = _paper_helpers()
        settings = load_settings()
        code = pt.run_once(settings)
        bot = get_bot_status(settings.runtime.log_dir)
        return {
            "ok": code == 0,
            "message": "Single cycle completed" if code == 0 else "Cycle completed with errors",
            "summary": bot.last_cycle_at or "",
            "actions": [],
        }

    @app.post("/api/bot/start")
    def bot_start() -> dict[str, Any]:
        settings = load_settings()
        try:
            settings.validate_for_trading()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        ok, message = start_bot(settings.runtime.log_dir)
        return {"ok": ok, "message": message}

    @app.post("/api/bot/stop")
    def bot_stop() -> dict[str, Any]:
        settings = load_settings()
        ok, message = stop_bot(settings.runtime.log_dir)
        return {"ok": ok, "message": message}

    @app.post("/api/bot/restart")
    def bot_restart() -> dict[str, Any]:
        settings = load_settings()
        stop_bot(settings.runtime.log_dir)
        try:
            settings.validate_for_trading()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        ok, message = start_bot(settings.runtime.log_dir)
        return {"ok": ok, "message": f"Restarted: {message}"}

    return app


app = create_app()
