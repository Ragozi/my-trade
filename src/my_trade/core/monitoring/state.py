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
    halt_lesson_logged: bool = False
    broker_sod_equity: float = 0.0

    @classmethod
    def empty(cls) -> DailyState:
        """Sentinel state that forces a rollover on the first cycle."""
        return cls(trading_day=_EPOCH, start_of_day_equity=0.0, peak_equity=0.0)

    def entries_for(self, symbol: str) -> int:
        return self.entries_today.get(normalize_symbol(symbol), 0)


def virtual_broker_scale(trading_capital: float, broker_equity: float) -> float:
    """Ratio mapping broker dollars to virtual ``TRADING_CAPITAL`` dollars."""
    if trading_capital <= 0 or broker_equity <= 0:
        return 1.0
    return trading_capital / broker_equity


def normalize_peak_equity(
    stored_peak: float,
    risk_equity: float,
    *,
    trading_capital: float | None,
    broker_equity: float,
    broker_sod_equity: float = 0.0,
) -> float:
    """Express peak on the same scale as ``risk_equity`` (for R4 circuit breaker).

    Peaks persisted before ``TRADING_CAPITAL`` was enabled are in full broker
    dollars; rescale them proportionally so a ~$105k paper peak becomes ~$15k.
    """
    if not trading_capital or trading_capital <= 0:
        return max(stored_peak, risk_equity)

    ref_broker = broker_sod_equity if broker_sod_equity > 0 else broker_equity
    peak = stored_peak
    stale = peak > trading_capital * 1.25 and peak > risk_equity * 1.5
    if stale and ref_broker > 0:
        peak = peak * virtual_broker_scale(trading_capital, ref_broker)

    return max(peak, risk_equity)


def resolve_risk_equity(
    broker_equity: float,
    state: DailyState,
    *,
    trading_capital: float | None,
) -> tuple[float, float, float]:
    """Map broker equity to the balance used for sizing and halt checks.

    Returns ``(risk_equity, day_pnl, start_of_day_equity)``.
    When ``trading_capital`` is set, day P&L is scaled proportionally from the
    broker account so a 10% paper loss ≈ 10% virtual loss on ``trading_capital``.
    """
    if trading_capital and trading_capital > 0 and state.broker_sod_equity > 0:
        scale = trading_capital / state.broker_sod_equity
        day_pnl = (broker_equity - state.broker_sod_equity) * scale
        risk_equity = trading_capital + day_pnl
        return risk_equity, day_pnl, trading_capital
    start = state.start_of_day_equity if state.start_of_day_equity > 0 else broker_equity
    return broker_equity, broker_equity - start, start


def rollover_if_new_day(
    state: DailyState,
    today: date,
    broker_equity: float,
    *,
    trading_capital: float | None = None,
) -> DailyState:
    """Reset daily counters when the trading day changes.

    Start-of-day equity is recaptured; the all-time peak is carried forward (the
    drawdown circuit breaker is measured from the lifetime high-water mark).
    """
    if state.trading_day == today:
        return state
    risk_sod = trading_capital if trading_capital and trading_capital > 0 else broker_equity
    prior_peak = state.peak_equity if state.peak_equity > 0 else risk_sod
    prior_peak = normalize_peak_equity(
        prior_peak,
        risk_sod,
        trading_capital=trading_capital,
        broker_equity=broker_equity,
        broker_sod_equity=broker_equity,
    )
    return DailyState(
        trading_day=today,
        start_of_day_equity=risk_sod,
        peak_equity=max(prior_peak, risk_sod),
        broker_sod_equity=broker_equity,
        entries_today={},
        position_stops={},
        entry_times={},
        halt_lesson_logged=False,
    )


def update_peak(state: DailyState, equity: float) -> DailyState:
    if equity <= state.peak_equity:
        return state
    return replace(state, peak_equity=equity)


def mark_halt_lesson_logged(state: DailyState) -> DailyState:
    return replace(state, halt_lesson_logged=True)


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
    *,
    trading_capital: float | None = None,
) -> AccountState:
    """Assemble the risk engine's ``AccountState`` from live + persisted data.

    Open risk uses the recorded stop per position; if a stop is unknown (e.g. a
    position opened outside this process) it falls back to a conservative
    ``fallback_stop_pct`` of the entry price.
    """
    equity, day_pnl, start_of_day = resolve_risk_equity(
        snapshot.equity,
        state,
        trading_capital=trading_capital,
    )
    peak = normalize_peak_equity(
        state.peak_equity,
        equity,
        trading_capital=trading_capital,
        broker_equity=snapshot.equity,
        broker_sod_equity=state.broker_sod_equity,
    )

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
