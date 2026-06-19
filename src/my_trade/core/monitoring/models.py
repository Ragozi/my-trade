"""Structured, log-free results of a trading cycle.

These let tests assert on *decisions* without parsing log lines, and let the
runnable script render them however it likes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class ActionKind(StrEnum):
    ENTRY_SUBMITTED = "entry_submitted"
    ENTRY_REJECTED = "entry_rejected"
    EXIT_SUBMITTED = "exit_submitted"
    EXIT_FAILED = "exit_failed"
    NO_SIGNAL = "no_signal"
    SKIP_OPEN_POSITION = "skip_open_position"
    SKIP_MAX_ENTRIES = "skip_max_entries"
    SESSION_CLOSED = "session_closed"
    HALT = "halt"
    ERROR = "error"


class HaltReason(StrEnum):
    CIRCUIT_BREAKER = "circuit_breaker"
    DAILY_LOSS_LIMIT = "daily_loss_limit"


@dataclass(frozen=True)
class CycleAction:
    kind: ActionKind
    symbol: str = ""
    detail: str = ""
    status: str = ""


@dataclass(frozen=True)
class CycleResult:
    timestamp: datetime
    equity: float
    day_pnl: float
    peak_equity: float
    open_positions: int
    halted: bool = False
    halt_reason: HaltReason | None = None
    actions: tuple[CycleAction, ...] = field(default_factory=tuple)

    @property
    def entries_submitted(self) -> int:
        return sum(1 for a in self.actions if a.kind is ActionKind.ENTRY_SUBMITTED)

    @property
    def exits_submitted(self) -> int:
        return sum(1 for a in self.actions if a.kind is ActionKind.EXIT_SUBMITTED)
