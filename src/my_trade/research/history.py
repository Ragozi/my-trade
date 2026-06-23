"""Parse journal events into trade outcomes and performance stats (pure logic)."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from my_trade.observability.journal import JournalEvent
from my_trade.research.models import ClosedTradeReflection, PerformanceSummary

_ENTRY_RE = re.compile(
    r"entry=([\d.]+).*stop=([\d.]+).*tp=([\d.]+)", re.IGNORECASE
)
_THESIS_RE = re.compile(r":\s*(.+)$")


@dataclass(frozen=True)
class PendingEntry:
    ts: str
    symbol: str
    detail: str
    entry_price: float | None
    equity: float | None


@dataclass(frozen=True)
class JournalTradeOutcome:
    """A closed round-trip inferred from journal entry + exit events."""

    symbol: str
    exit_ts: str
    exit_reason: str
    entry_detail: str
    entry_price: float | None
    equity_at_exit: float | None
    day_pnl_at_exit: float | None
    thesis_at_entry: str = ""


def parse_entry_prices(detail: str) -> float | None:
    match = _ENTRY_RE.search(detail)
    if not match:
        return None
    return float(match.group(1))


def parse_research_thesis(detail: str) -> str:
    """Extract thesis text from a research_proposal journal detail line."""
    match = _THESIS_RE.search(detail)
    return match.group(1).strip() if match else detail


def classify_outcome(exit_reason: str, pnl_estimate: float | None) -> str:
    reason = exit_reason.lower()
    if reason in ("take_profit", "tp"):
        return "win"
    if reason in ("stop_loss", "stop"):
        return "loss"
    if pnl_estimate is not None:
        if pnl_estimate > 1.0:
            return "win"
        if pnl_estimate < -1.0:
            return "loss"
        return "flat"
    if reason in ("rsi_overbought", "time_stop"):
        return "flat"
    return "unknown"


def summarize_reflection(
    *,
    symbol: str,
    outcome: str,
    exit_reason: str,
    pnl_estimate: float | None,
    thesis_at_entry: str,
) -> str:
    pnl_part = f" est P&L ${pnl_estimate:+.2f}" if pnl_estimate is not None else ""
    thesis_part = f" Thesis: {thesis_at_entry[:120]}." if thesis_at_entry else ""
    played = (
        "Thesis largely played out."
        if outcome == "win"
        else "Thesis did not play out."
        if outcome == "loss"
        else "Mixed / timed exit."
    )
    return (
        f"{symbol} closed via {exit_reason} ({outcome}){pnl_part}.{thesis_part} {played}"
    )


def pair_trades_from_events(
    events: Sequence[JournalEvent],
    *,
    symbols: frozenset[str] | None = None,
) -> list[JournalTradeOutcome]:
    """Walk journal events chronologically and pair entry_submitted with exit_submitted."""
    pending: dict[str, PendingEntry] = {}
    last_thesis: dict[str, str] = {}
    outcomes: list[JournalTradeOutcome] = []

    for event in sorted(events, key=lambda e: e.ts):
        sym = event.symbol.upper()
        if symbols and sym and sym not in symbols:
            continue
        if event.kind == "research_proposal" and sym:
            last_thesis[sym] = parse_research_thesis(event.detail)
        elif event.kind == "entry_submitted" and sym:
            pending[sym] = PendingEntry(
                ts=event.ts,
                symbol=sym,
                detail=event.detail,
                entry_price=parse_entry_prices(event.detail),
                equity=event.equity,
            )
        elif event.kind == "exit_submitted" and sym:
            entry = pending.pop(sym, None)
            outcomes.append(
                JournalTradeOutcome(
                    symbol=sym,
                    exit_ts=event.ts,
                    exit_reason=event.detail,
                    entry_detail=entry.detail if entry else "",
                    entry_price=entry.entry_price if entry else None,
                    equity_at_exit=event.equity,
                    day_pnl_at_exit=event.day_pnl,
                    thesis_at_entry=last_thesis.get(sym, ""),
                )
            )
    return outcomes


def journal_outcome_to_reflection(outcome: JournalTradeOutcome) -> ClosedTradeReflection:
    pnl: float | None = None
    if outcome.equity_at_exit is not None and outcome.entry_price is not None:
        # Rough proxy when we lack fill prices: use day_pnl delta unavailable per trade.
        pnl = None
    outcome_label = classify_outcome(outcome.exit_reason, pnl)
    closed_at = datetime.fromisoformat(outcome.exit_ts)
    summary = summarize_reflection(
        symbol=outcome.symbol,
        outcome=outcome_label,
        exit_reason=outcome.exit_reason,
        pnl_estimate=pnl,
        thesis_at_entry=outcome.thesis_at_entry,
    )
    return ClosedTradeReflection(
        symbol=outcome.symbol,
        closed_at=closed_at,
        outcome=outcome_label,  # type: ignore[arg-type]
        pnl_estimate=pnl,
        exit_reason=outcome.exit_reason,
        entry_price=outcome.entry_price,
        thesis_at_entry=outcome.thesis_at_entry,
        summary=summary,
    )


def compute_performance(
    reflections: Sequence[ClosedTradeReflection],
    *,
    window: int = 20,
) -> PerformanceSummary:
    recent = list(reflections)[-window:]
    wins = sum(1 for r in recent if r.outcome == "win")
    losses = sum(1 for r in recent if r.outcome == "loss")
    flats = sum(1 for r in recent if r.outcome == "flat")
    decided = wins + losses
    pnls = [r.pnl_estimate for r in recent if r.pnl_estimate is not None]
    return PerformanceSummary(
        sample_size=len(recent),
        wins=wins,
        losses=losses,
        flats=flats,
        win_rate=(wins / decided) if decided else 0.0,
        avg_pnl_estimate=(sum(pnls) / len(pnls)) if pnls else 0.0,
    )
