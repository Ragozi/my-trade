"""Monitoring loop (deterministic). Phase 1 migration target for `main.py`'s loop.

Responsibilities:
  - Scheduler (e.g. 60s scan cycle).
  - Orchestrate: risk pre-checks -> data -> strategy -> risk sizing -> execution.
  - Manage open positions (time-stop, RSI exit) beyond the broker bracket.
  - Restart-safe daily state (no duplicate entries after a crash/restart).

Fail-safe: on any error/ambiguity/stale data, skip the cycle (do nothing).

NOTE: ``AlpacaAccountProvider`` is intentionally NOT imported here so importing
this package does not require the alpaca SDK. Import it directly from
``my_trade.core.monitoring.alpaca_account`` when wiring the live loop.
"""

from .account import AccountProvider, AccountSnapshot, Position
from .models import ActionKind, CycleAction, CycleResult, HaltReason
from .orchestrator import Executor, StrategyEngine, TradingOrchestrator
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

__all__ = [
    "AccountProvider",
    "AccountSnapshot",
    "ActionKind",
    "CycleAction",
    "CycleResult",
    "DailyState",
    "DailyStateStore",
    "Executor",
    "HaltReason",
    "Position",
    "StrategyEngine",
    "TradingOrchestrator",
    "build_account_state",
    "clear_position",
    "entry_time_for",
    "record_entry",
    "rollover_if_new_day",
    "update_peak",
]
