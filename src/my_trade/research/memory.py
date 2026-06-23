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
    compute_performance,
    pair_trades_from_events,
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

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "reflections": [r.model_dump(mode="json") for r in self._reflections],
            "thesis_cache": self._thesis_by_symbol,
        }
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def note_proposals(self, ideas: Sequence[TradeIdea]) -> None:
        """Cache latest Claude thesis per symbol from the current proposal batch."""
        for idea in ideas:
            if idea.thesis:
                self._thesis_by_symbol[idea.symbol.upper()] = idea.thesis

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
        self._reflections.append(reflection)
        if len(self._reflections) > self.max_reflections:
            self._reflections = self._reflections[-self.max_reflections :]
        self._save()
        return reflection

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

    def enrich_from_journal(
        self,
        journal_path: str | Path,
        *,
        candidate_symbols: Sequence[str],
        limit_events: int = 500,
    ) -> None:
        """Backfill memory from journal pairs when the store is empty or sparse."""
        if len(self._reflections) >= self.performance_window:
            return
        sym_set = frozenset(s.upper() for s in candidate_symbols)
        journal = Journal(journal_path)
        try:
            events = journal.fetch_recent(limit_events)
            events.reverse()
            from my_trade.research.history import journal_outcome_to_reflection

            for outcome in pair_trades_from_events(events, symbols=sym_set):
                ref = journal_outcome_to_reflection(outcome)
                if ref.symbol not in {r.symbol for r in self._reflections}:
                    self._reflections.append(ref)
            if len(self._reflections) > self.max_reflections:
                self._reflections = self._reflections[-self.max_reflections :]
            self._save()
        finally:
            journal.close()
