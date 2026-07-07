"""Pure serializers: internal Settings / journal → frontend JSON contract.

No I/O here — keeps the API response shapes unit-testable and aligned with
frontend/src/lib/types.ts.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, date, datetime
from typing import Any

from my_trade.config.settings import Settings
from my_trade.core.monitoring.state import DailyState
from my_trade.core.screening import Candidate
from my_trade.observability.journal import JournalEvent


def settings_to_config(settings: Settings) -> dict[str, Any]:
    """Map ``Settings`` to the Lovable ``AppConfig`` shape."""
    sc = settings.screener
    return {
        "asset_class": settings.asset_class,
        "symbols": list(settings.symbols),
        "paper_trading": settings.alpaca.paper_trading,
        "screener": {
            "enabled": sc.enabled,
            "top_n": sc.top_n,
            "refresh_seconds": sc.refresh_seconds,
            "min_atr_pct": sc.min_atr_pct,
            "min_dollar_volume": sc.min_dollar_volume,
            "use_movers": sc.use_movers,
            "movers_source": sc.movers_source,
        },
        "strategy": {
            "rsi_oversold": settings.strategy.rsi_oversold,
            "rsi_overbought": settings.strategy.rsi_overbought,
            "stop_loss_pct": settings.strategy.stop_loss_pct,
            "take_profit_pct": settings.strategy.take_profit_pct,
            "max_hold_minutes": settings.strategy.max_hold_minutes,
            "require_15m_uptrend": settings.strategy.require_15m_uptrend,
            "require_volume_spike": settings.strategy.require_volume_spike,
        },
        "risk": {
            "max_risk_per_trade_pct": settings.risk.max_risk_per_trade_pct,
            "max_open_risk_pct": settings.risk.max_total_open_risk_pct,
            "daily_loss_limit_pct": settings.risk.daily_loss_limit_pct,
            "daily_profit_target_pct": settings.risk.daily_profit_target_pct,
            "max_drawdown_pct": settings.risk.max_drawdown_pct,
            "max_concurrent_positions": settings.risk.max_concurrent_positions,
            "max_daily_entries": settings.risk.max_daily_entries,
            "max_entries_per_symbol_per_day": settings.risk.max_entries_per_symbol_per_day,
            "trading_capital": settings.risk.trading_capital,
            "max_notional_pct": settings.risk.max_notional_pct,
        },
        "runtime": {
            "scan_interval_seconds": settings.runtime.scan_interval_seconds,
            "log_level": "INFO",
        },
        "research": {
            "enabled": settings.research.enabled,
            "active": (
                settings.research.enabled
                and (
                    not settings.research.equities_only or settings.is_equities
                )
            ),
            "require_approval": settings.research.require_approval_for_entry,
            "model": settings.research.model,
            "call_interval_seconds": settings.research.min_interval_seconds,
        },
    }


def event_to_json(event: JournalEvent) -> dict[str, Any]:
    return {
        "ts": event.ts,
        "kind": event.kind,
        "symbol": event.symbol or None,
        "detail": event.detail,
        "equity": event.equity,
        "day_pnl": event.day_pnl,
    }


def stats_from_events(
    events: list[JournalEvent],
    daily_state: DailyState | None,
    latest_equity: tuple[float, float] | None,
    *,
    today: date | None = None,
) -> dict[str, Any]:
    """Aggregate journal rows into the frontend ``Stats`` shape."""
    day = today or datetime.now(UTC).date()
    day_prefix = day.isoformat()
    today_events = [e for e in events if e.ts.startswith(day_prefix)]
    counts = Counter(e.kind for e in today_events)
    state = daily_state
    return {
        "today": {
            "entries": counts.get("entry_submitted", 0),
            "exits": counts.get("exit_submitted", 0),
            "halts": counts.get("halt", 0),
            "errors": counts.get("error", 0),
            "research_proposals": counts.get("research_proposal", 0),
            "research_skipped": counts.get("research_skipped", 0),
            "research_reflections": counts.get("research_reflection", 0),
        },
        "daily_state": {
            "trading_day": state.trading_day.isoformat() if state else day_prefix,
            "start_of_day_equity": state.start_of_day_equity if state else 0.0,
            "peak_equity": state.peak_equity if state else 0.0,
            "entries_today": dict(state.entries_today) if state else {},
        },
        "latest_equity": (
            {"equity": latest_equity[0], "day_pnl": latest_equity[1]}
            if latest_equity is not None
            else None
        ),
    }


def watchlist_to_json(
    symbols: list[str],
    ranked: list[Candidate],
    *,
    refreshed_at: datetime | None,
    universe_source: str,
    knowledge: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "symbols": symbols,
        "ranked": [
            {
                "symbol": c.symbol,
                "atr_pct": c.atr_pct,
                "dollar_volume": c.dollar_volume,
                "score": c.score,
            }
            for c in ranked
        ],
        "knowledge": knowledge or [],
        "refreshed_at": refreshed_at.isoformat() if refreshed_at else None,
        "universe_source": universe_source,
    }
