"""TradingOrchestrator: the thin loop that coordinates the deterministic core.

It owns *sequencing and daily state*, not trading math — every decision is
delegated to already-tested pure layers:

    Data (bars)  ->  Strategy (signal/exit)  ->  Risk (gate, inside execution)
                                              ->  Execution (orders)

Safety invariants preserved here:
  * Exits are managed every cycle, even when new entries are halted.
  * No entry is ever sent without the risk gate approving (the execution adapter
    re-runs ``evaluate_trade``); the orchestrator additionally halts entries on
    circuit-breaker / daily-loss.
  * Daily state is persisted after every mutation so restarts never double-count.
  * No research/Claude calls (Phase 4).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol

import pandas as pd

from my_trade.core.execution import EntryIntent, ExecutionOutcome
from my_trade.core.risk import (
    RiskLimits,
    is_circuit_breaker_tripped,
    is_daily_loss_limit_hit,
)
from my_trade.data import MarketDataProvider, normalize_symbol

from .account import AccountProvider, AccountSnapshot
from .models import ActionKind, CycleAction, CycleResult, HaltReason
from .state import (
    DailyState,
    build_account_state,
    clear_position,
    entry_time_for,
    record_entry,
    rollover_if_new_day,
    update_peak,
)
from .store import DailyStateStore

if TYPE_CHECKING:
    from my_trade.core.risk import AccountState
    from my_trade.core.strategy.models import ScanEvaluation, Signal


class StrategyEngine(Protocol):
    def detect_entry(
        self,
        symbol: str,
        df_1m: pd.DataFrame,
        df_5m: pd.DataFrame,
        df_15m: pd.DataFrame,
        now: datetime | None = None,
    ) -> tuple[Signal | None, ScanEvaluation]: ...

    def detect_exit(
        self,
        df_1m: pd.DataFrame,
        entry_time: datetime,
        entry_price: float,
        now: datetime,
    ) -> str | None: ...


class Executor(Protocol):
    def execute_entry(
        self,
        intent: EntryIntent,
        account: AccountState,
        *,
        now: datetime | None = None,
    ) -> ExecutionOutcome: ...

    def close_position(self, symbol: str, *, now: datetime | None = None) -> ExecutionOutcome: ...


def _utcnow() -> datetime:
    return datetime.now(UTC)


class TradingOrchestrator:
    """Coordinates one scan cycle across the deterministic core layers."""

    def __init__(
        self,
        *,
        data: MarketDataProvider,
        strategy: StrategyEngine,
        execution: Executor,
        account: AccountProvider,
        store: DailyStateStore,
        limits: RiskLimits,
        symbols: Sequence[str],
        entry_timeframe: str = "1Min",
        trend_timeframe: str = "5Min",
        trend_timeframe_15m: str = "15Min",
        bar_limit: int = 200,
        max_entries_per_symbol_per_day: int = 10,
        fallback_stop_pct: float = 0.0065,
        watchlist: Callable[[], Sequence[str]] | None = None,
        clock: Callable[[], datetime] = _utcnow,
        logger: logging.Logger | None = None,
    ) -> None:
        self._data = data
        self._strategy = strategy
        self._execution = execution
        self._account = account
        self._store = store
        self._limits = limits
        self._symbols = tuple(symbols)
        self._watchlist = watchlist
        self._entry_tf = entry_timeframe
        self._trend_tf = trend_timeframe
        self._trend_tf_15m = trend_timeframe_15m
        self._bar_limit = bar_limit
        self._max_entries = max_entries_per_symbol_per_day
        self._fallback_stop_pct = fallback_stop_pct
        self._clock = clock
        self._log = logger or logging.getLogger("my_trade.monitoring")
        self._state: DailyState = self._store.load() or DailyState.empty()

    @property
    def state(self) -> DailyState:
        return self._state

    def _persist(self, state: DailyState) -> None:
        self._state = state
        self._store.save(state)

    def _get_bars(self, symbol: str, timeframe: str) -> pd.DataFrame:
        return self._data.get_bars(symbol, timeframe, self._bar_limit)

    def _active_symbols(self) -> tuple[str, ...]:
        """Symbols to scan this cycle.

        When a dynamic ``watchlist`` (e.g. the screener) is configured we use it,
        but fail safe to the statically configured symbols if it errors or is
        empty — the screener narrowing the universe must never *halt* trading.
        """
        if self._watchlist is None:
            return self._symbols
        try:
            selected = tuple(self._watchlist())
        except Exception as exc:
            self._log.warning("watchlist failed, using static symbols: %s", exc)
            return self._symbols
        if not selected:
            self._log.debug("watchlist empty this cycle; nothing to scan")
            return ()
        return selected

    def run_cycle(self, now: datetime | None = None) -> CycleResult:
        when = now or self._clock()
        actions: list[CycleAction] = []

        try:
            snapshot = self._account.get_snapshot()
        except Exception as exc:  # fail safe: no account state => do nothing
            self._log.error("account snapshot failed: %s", exc)
            return CycleResult(
                timestamp=when,
                equity=0.0,
                day_pnl=0.0,
                peak_equity=self._state.peak_equity,
                open_positions=0,
                actions=(CycleAction(ActionKind.ERROR, detail=str(exc)),),
            )

        # Daily rollover + peak tracking, persisted before any decision.
        state = rollover_if_new_day(self._state, when.date(), snapshot.equity)
        state = update_peak(state, snapshot.equity)
        self._persist(state)

        account_state = build_account_state(snapshot, state, self._fallback_stop_pct)
        day_pnl = account_state.realized_day_pnl

        # (1) Manage exits first — always, even if entries are halted.
        actions.extend(self._manage_exits(snapshot, when))

        # (2) Halt gate for NEW entries.
        halt_reason = self._halt_reason(account_state)
        if halt_reason is not None:
            self._log.warning("entries halted: %s", halt_reason.value)
            actions.append(CycleAction(ActionKind.HALT, detail=halt_reason.value))
            return CycleResult(
                timestamp=when,
                equity=account_state.equity,
                day_pnl=day_pnl,
                peak_equity=account_state.peak_equity,
                open_positions=account_state.open_positions,
                halted=True,
                halt_reason=halt_reason,
                actions=tuple(actions),
            )

        # (3) Entries.
        open_symbols = {normalize_symbol(p.symbol) for p in snapshot.positions}
        actions.extend(self._scan_entries(open_symbols, account_state, when))

        return CycleResult(
            timestamp=when,
            equity=account_state.equity,
            day_pnl=day_pnl,
            peak_equity=account_state.peak_equity,
            open_positions=account_state.open_positions,
            actions=tuple(actions),
        )

    def _halt_reason(self, account_state: AccountState) -> HaltReason | None:
        if is_circuit_breaker_tripped(account_state, self._limits):
            return HaltReason.CIRCUIT_BREAKER
        if is_daily_loss_limit_hit(account_state, self._limits):
            return HaltReason.DAILY_LOSS_LIMIT
        return None

    def _manage_exits(self, snapshot: AccountSnapshot, when: datetime) -> list[CycleAction]:
        actions: list[CycleAction] = []
        for pos in snapshot.positions:
            bars = self._get_bars(pos.symbol, self._entry_tf)
            entry_time = entry_time_for(self._state, pos.symbol) or when
            reason = self._strategy.detect_exit(
                bars, entry_time, pos.avg_entry_price, when
            )
            if reason is None:
                continue
            outcome = self._execution.close_position(pos.symbol, now=when)
            if outcome.submitted:
                self._persist(clear_position(self._state, pos.symbol))
                self._log.info("EXIT %s (%s)", pos.symbol, reason)
                actions.append(CycleAction(ActionKind.EXIT_SUBMITTED, pos.symbol, reason))
            else:
                self._log.error("exit failed for %s: %s", pos.symbol, outcome.detail)
                actions.append(
                    CycleAction(ActionKind.EXIT_FAILED, pos.symbol, outcome.detail)
                )
        return actions

    def _scan_entries(
        self,
        open_symbols: set[str],
        account_state: AccountState,
        when: datetime,
    ) -> list[CycleAction]:
        actions: list[CycleAction] = []
        for symbol in self._active_symbols():
            if normalize_symbol(symbol) in open_symbols:
                actions.append(CycleAction(ActionKind.SKIP_OPEN_POSITION, symbol))
                continue
            if self._state.entries_for(symbol) >= self._max_entries:
                actions.append(CycleAction(ActionKind.SKIP_MAX_ENTRIES, symbol))
                continue

            signal, evaluation = self._strategy.detect_entry(
                symbol,
                self._get_bars(symbol, self._entry_tf),
                self._get_bars(symbol, self._trend_tf),
                self._get_bars(symbol, self._trend_tf_15m),
                when,
            )
            if signal is None:
                self._log.debug("no signal %s: %s", symbol, evaluation.summary)
                actions.append(CycleAction(ActionKind.NO_SIGNAL, symbol, evaluation.summary))
                continue

            outcome = self._execution.execute_entry(
                EntryIntent.from_signal(signal), account_state, now=when
            )
            if outcome.submitted:
                self._persist(record_entry(self._state, symbol, signal.stop_price, when))
                self._log.info(
                    "ENTRY %s @ %.2f stop %.2f tp %.2f conf %.2f",
                    symbol,
                    signal.entry_price,
                    signal.stop_price,
                    signal.take_profit_price,
                    signal.confidence,
                )
                detail = (
                    f"entry={signal.entry_price:.2f} stop={signal.stop_price:.2f} "
                    f"tp={signal.take_profit_price:.2f} conf={signal.confidence:.2f}"
                )
                actions.append(
                    CycleAction(
                        ActionKind.ENTRY_SUBMITTED, symbol, detail, outcome.status.value
                    )
                )
            else:
                self._log.info("entry rejected %s: %s", symbol, outcome.detail)
                actions.append(
                    CycleAction(
                        ActionKind.ENTRY_REJECTED,
                        symbol,
                        outcome.detail,
                        outcome.status.value,
                    )
                )
        return actions
