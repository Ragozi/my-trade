"""Daily trading state: pure, restart-safe, and the bridge to the risk engine.

Design choice for restart-safety: **day P&L is derived, never accumulated**.
``day_pnl = equity - start_of_day_equity`` is a pure function of current equity
and the persisted start-of-day value, so a crash/restart can never double-count
realized losses. We persist only the inputs (start-of-day equity, all-time peak,
per-symbol entry counts, and the stops/entry-times of open positions).

Note: the derived day P&L includes unrealized P&L of open positions, which makes
the daily-loss check *more* conservative (it trips on drawdown, not just closed
losses) — a deliberately safe bias.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, datetime

from my_trade.core.risk import AccountState
from my_trade.data import normalize_symbol

from .account import AccountSnapshot

_EPOCH = date(1970, 1, 1)


@dataclass(frozen=True)
class DailyState:
    """Persisted, restart-safe daily counters. All symbols are normalized."""

    trading_day: date
    start_of_day_equity: float
    peak_equity: float
    entries_today: dict[str, int] = field(default_factory=dict)
    position_stops: dict[str, float] = field(default_factory=dict)
    entry_times: dict[str, str] = field(default_factory=dict)

    @classmethod
    def empty(cls) -> DailyState:
        """Sentinel state that forces a rollover on the first cycle."""
        return cls(trading_day=_EPOCH, start_of_day_equity=0.0, peak_equity=0.0)

    def entries_for(self, symbol: str) -> int:
        return self.entries_today.get(normalize_symbol(symbol), 0)


def rollover_if_new_day(state: DailyState, today: date, equity: float) -> DailyState:
    """Reset daily counters when the trading day changes.

    Start-of-day equity is recaptured; the all-time peak is carried forward (the
    drawdown circuit breaker is measured from the lifetime high-water mark).
    """
    if state.trading_day == today:
        return state
    return DailyState(
        trading_day=today,
        start_of_day_equity=equity,
        peak_equity=max(state.peak_equity, equity),
        entries_today={},
        position_stops={},
        entry_times={},
    )


def update_peak(state: DailyState, equity: float) -> DailyState:
    if equity <= state.peak_equity:
        return state
    return replace(state, peak_equity=equity)


def record_entry(
    state: DailyState,
    symbol: str,
    stop_price: float,
    entry_time: datetime,
) -> DailyState:
    key = normalize_symbol(symbol)
    return replace(
        state,
        entries_today={**state.entries_today, key: state.entries_today.get(key, 0) + 1},
        position_stops={**state.position_stops, key: stop_price},
        entry_times={**state.entry_times, key: entry_time.isoformat()},
    )


def clear_position(state: DailyState, symbol: str) -> DailyState:
    key = normalize_symbol(symbol)
    stops = {k: v for k, v in state.position_stops.items() if k != key}
    times = {k: v for k, v in state.entry_times.items() if k != key}
    return replace(state, position_stops=stops, entry_times=times)


def entry_time_for(state: DailyState, symbol: str) -> datetime | None:
    raw = state.entry_times.get(normalize_symbol(symbol))
    if raw is None:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def build_account_state(
    snapshot: AccountSnapshot,
    state: DailyState,
    fallback_stop_pct: float,
) -> AccountState:
    """Assemble the risk engine's ``AccountState`` from live + persisted data.

    Open risk uses the recorded stop per position; if a stop is unknown (e.g. a
    position opened outside this process) it falls back to a conservative
    ``fallback_stop_pct`` of the entry price.
    """
    equity = snapshot.equity
    start_of_day = state.start_of_day_equity if state.start_of_day_equity > 0 else equity
    day_pnl = equity - start_of_day
    peak = max(state.peak_equity, equity)

    open_risk = 0.0
    for pos in snapshot.positions:
        key = normalize_symbol(pos.symbol)
        stop = state.position_stops.get(key)
        if stop is None or stop <= 0 or stop >= pos.avg_entry_price:
            stop = pos.avg_entry_price * (1.0 - fallback_stop_pct)
        open_risk += (pos.avg_entry_price - stop) * abs(pos.qty)

    return AccountState(
        equity=equity,
        start_of_day_equity=start_of_day,
        peak_equity=peak,
        realized_day_pnl=day_pnl,
        open_positions=len(snapshot.positions),
        open_risk_dollars=open_risk,
    )
