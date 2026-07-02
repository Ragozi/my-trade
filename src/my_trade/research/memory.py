"""Lightweight JSON memory store for Claude research reflections."""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from my_trade.observability.journal import Journal
from my_trade.research.history import (
    all_closed_trades_from_events,
    compute_performance,
    journal_outcome_to_reflection,
)
from my_trade.research.models import ClosedTradeReflection, PerformanceSummary, TradeIdea
from my_trade.research.postmortem import PostMortemGenerator
from my_trade.research.reflection import build_reflection

_log = logging.getLogger("my_trade.research.memory")


@dataclass
class ResearchMemoryStore:
    """Append-only reflection log + per-symbol thesis cache (in-memory + JSON file)."""

    path: Path
    max_reflections: int = 100
    performance_window: int = 20
    postmortem: PostMortemGenerator | None = None
    _reflections: list[ClosedTradeReflection] = field(default_factory=list)
    _thesis_by_symbol: dict[str, str] = field(default_factory=dict)
    _stance_by_symbol: dict[str, TradeIdea] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.path = Path(self.path)
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            _log.warning("could not load research memory %s: %s", self.path, exc)
            return
        items = raw.get("reflections") or []
        for item in items:
            try:
                self._reflections.append(ClosedTradeReflection.model_validate(item))
            except Exception as exc:
                _log.debug("skip invalid reflection: %s", exc)
        self._thesis_by_symbol = {
            str(k).upper(): str(v) for k, v in (raw.get("thesis_cache") or {}).items()
        }
        for sym, item in (raw.get("stance_cache") or {}).items():
            try:
                self._stance_by_symbol[str(sym).upper()] = TradeIdea.model_validate(item)
            except Exception as exc:
                _log.debug("skip invalid stance for %s: %s", sym, exc)

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "reflections": [r.model_dump(mode="json") for r in self._reflections],
            "thesis_cache": self._thesis_by_symbol,
            "stance_cache": {
                sym: idea.model_dump(mode="json")
                for sym, idea in self._stance_by_symbol.items()
            },
        }
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def _reflection_key(self, reflection: ClosedTradeReflection) -> str:
        return (
            f"{reflection.symbol}:{reflection.closed_at.date().isoformat()}:"
            f"{reflection.exit_reason}"
        )

    def _append_reflection(self, reflection: ClosedTradeReflection) -> ClosedTradeReflection | None:
        key = self._reflection_key(reflection)
        if key in {self._reflection_key(r) for r in self._reflections}:
            return None
        self._reflections.append(reflection)
        if len(self._reflections) > self.max_reflections:
            self._reflections = self._reflections[-self.max_reflections :]
        self._save()
        return reflection

    def note_proposals(self, ideas: Sequence[TradeIdea]) -> None:
        """Cache latest research thesis and stance per symbol from proposals."""
        for idea in ideas:
            sym = idea.symbol.upper()
            self._stance_by_symbol[sym] = idea
            if idea.thesis:
                self._thesis_by_symbol[sym] = idea.thesis
        self._save()

    @property
    def thesis_cache(self) -> dict[str, str]:
        return dict(self._thesis_by_symbol)

    def stance_for_symbol(self, symbol: str) -> TradeIdea | None:
        """Last known research stance — used when the current cycle skipped research."""
        return self._stance_by_symbol.get(symbol.upper())

    def record_close(
        self,
        *,
        symbol: str,
        exit_reason: str,
        entry_price: float,
        qty: float,
        unrealized_pl: float,
        closed_at: datetime,
    ) -> ClosedTradeReflection:
        thesis = self._thesis_by_symbol.get(symbol.upper(), "")
        reflection = build_reflection(
            symbol=symbol,
            exit_reason=exit_reason,
            entry_price=entry_price,
            qty=qty,
            unrealized_pl=unrealized_pl,
            thesis_at_entry=thesis,
            closed_at=closed_at,
        )
        if self.postmortem is not None:
            reflection = self.postmortem.maybe_enrich(reflection, when=closed_at)
        return self._append_reflection(reflection) or reflection

    def record_broker_close(
        self,
        *,
        symbol: str,
        entry_price: float,
        qty: float,
        pnl_estimate: float,
        closed_at: datetime,
        entry_count: int = 1,
    ) -> ClosedTradeReflection | None:
        """Record a loss learned when the broker closed a position we did not exit cleanly."""
        exit_reason = "broker_close"
        stacked = f" ({entry_count} entries today)" if entry_count > 1 else ""
        thesis = self._thesis_by_symbol.get(symbol.upper(), "")
        reflection = build_reflection(
            symbol=symbol,
            exit_reason=exit_reason,
            entry_price=entry_price,
            qty=qty,
            unrealized_pl=pnl_estimate,
            thesis_at_entry=thesis,
            closed_at=closed_at,
        )
        reflection = reflection.model_copy(
            update={
                "summary": (
                    f"{symbol.upper()} closed at broker (bracket/stop){stacked} "
                    f"({reflection.outcome}) est P&L ${pnl_estimate:+.2f}. "
                    f"Thesis did not play out."
                    + (f" Thesis: {thesis[:120]}." if thesis else "")
                )
            }
        )
        if self.postmortem is not None:
            reflection = self.postmortem.maybe_enrich(reflection, when=closed_at)
        return self._append_reflection(reflection)

    def record_session_halt(
        self,
        *,
        halt_reason: str,
        day_pnl: float,
        equity: float,
        closed_at: datetime,
    ) -> ClosedTradeReflection | None:
        """One lesson per halted session — captures day-level loss patterns."""
        outcome = "loss" if day_pnl < -1.0 else "flat" if abs(day_pnl) <= 1.0 else "win"
        summary = (
            f"Session halted ({halt_reason}). Day P&L ${day_pnl:+.2f} on ${equity:,.0f} equity. "
            "Review recent reflections and journal before next session."
        )
        reflection = ClosedTradeReflection(
            symbol="SESSION",
            closed_at=closed_at,
            outcome=outcome,  # type: ignore[arg-type]
            pnl_estimate=day_pnl,
            exit_reason=halt_reason,
            summary=summary,
        )
        if self.postmortem is not None:
            reflection = self.postmortem.maybe_enrich(reflection, when=closed_at)
        return self._append_reflection(reflection)

    def recent_reflections(
        self,
        *,
        limit: int = 10,
        symbols: frozenset[str] | None = None,
    ) -> tuple[ClosedTradeReflection, ...]:
        items = self._reflections
        if symbols:
            items = [r for r in items if r.symbol in symbols]
        return tuple(items[-limit:])

    def performance_summary(
        self,
        *,
        symbols: frozenset[str] | None = None,
    ) -> PerformanceSummary:
        items = self._reflections
        if symbols:
            items = [r for r in items if r.symbol in symbols]
        return compute_performance(items, window=self.performance_window)

    def sync_from_journal(
        self,
        journal_path: str | Path,
        *,
        candidate_symbols: Sequence[str],
        limit_events: int = 1000,
    ) -> int:
        """Import any closed trades from the journal not yet in memory (incl. broker closes)."""
        sym_set = frozenset(s.upper() for s in candidate_symbols)
        journal = Journal(journal_path)
        added = 0
        try:
            events = journal.fetch_recent(limit_events)
            events.reverse()
            existing = {self._reflection_key(r) for r in self._reflections}
            for outcome in all_closed_trades_from_events(events, symbols=sym_set):
                ref = journal_outcome_to_reflection(outcome)
                key = self._reflection_key(ref)
                if key in existing:
                    continue
                if self.postmortem is not None:
                    ref = self.postmortem.maybe_enrich(ref, when=ref.closed_at)
                self._reflections.append(ref)
                existing.add(key)
                added += 1
            if added:
                if len(self._reflections) > self.max_reflections:
                    self._reflections = self._reflections[-self.max_reflections :]
                self._save()
        finally:
            journal.close()
        return added

    def enrich_from_journal(
        self,
        journal_path: str | Path,
        *,
        candidate_symbols: Sequence[str],
        limit_events: int = 500,
    ) -> None:
        """Backfill memory from journal pairs and inferred broker closes."""
        self.sync_from_journal(
            journal_path,
            candidate_symbols=candidate_symbols,
            limit_events=limit_events,
        )
