"""Structured trade knowledge base — every transaction, win/loss, why and how.

Persisted to JSON and injected into research prompts so Claude (and other LLM tiers)
have a durable reference log of what happened and what to do differently.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from my_trade.observability.journal import Journal, JournalEvent
from my_trade.research.gating import idea_for_symbol
from my_trade.research.history import (
    all_closed_trades_from_events,
    classify_outcome,
    parse_entry_prices,
    parse_research_thesis,
    summarize_reflection,
)
from my_trade.research.models import ClaudeProposal, ClosedTradeReflection

_log = logging.getLogger("my_trade.research.knowledge")

EventKind = Literal[
    "entry",
    "exit",
    "entry_rejected",
    "research_veto",
    "exit_failed",
    "research_reflection",
    "session_halt",
    "no_signal",
]

_JOURNAL_KIND_MAP: dict[str, EventKind | None] = {
    "entry_submitted": "entry",
    "exit_submitted": "exit",
    "entry_rejected": "entry_rejected",
    "research_not_approved": "research_veto",
    "exit_failed": "exit_failed",
    "research_reflection": "research_reflection",
    "halt": "session_halt",
}


class TradeKnowledgeRecord(BaseModel):
    """One documented event in the trading knowledge log."""

    id: str
    ts: datetime
    trading_day: date
    event_kind: EventKind
    symbol: str = ""
    outcome: Literal["win", "loss", "flat", "unknown", "n/a"] = "n/a"
    pnl_estimate: float | None = None
    equity: float | None = None
    day_pnl: float | None = None
    what_happened: str = ""
    how_it_happened: str = ""
    why_it_happened: str = ""
    research_action: str | None = None
    research_confidence: float | None = None
    research_thesis: str | None = None
    strategy_detail: str | None = None
    lessons: tuple[str, ...] = ()


class DailyKnowledgeSummary(BaseModel):
    trading_day: date
    closed_at: datetime
    virtual_equity: float | None = None
    day_pnl: float | None = None
    entries: int = 0
    exits: int = 0
    wins: int = 0
    losses: int = 0
    flats: int = 0
    key_lessons: tuple[str, ...] = ()
    narrative: str = ""


def record_id(*parts: str) -> str:
    raw = "|".join(p for p in parts if p)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _parse_research_line(detail: str) -> dict[str, Any]:
    match = re.match(
        r"^\[(?P<provider>[^\]]+)\]\s+"
        r"(?P<action>long|hold|avoid)\s+"
        r"conf=(?P<confidence>[\d.]+)\s+"
        r"(?P<instrument>\w+)\s+"
        r"(?P<horizon>\w+):\s*(?P<thesis>.*)$",
        detail.strip(),
        re.IGNORECASE,
    )
    if not match:
        return {}
    return {
        "provider": match.group("provider"),
        "action": match.group("action").lower(),
        "confidence": float(match.group("confidence")),
        "instrument": match.group("instrument").lower(),
        "horizon": match.group("horizon").lower(),
        "thesis": match.group("thesis").strip(),
    }


class TradeKnowledgeStore:
    """Append-only structured knowledge log (JSON file)."""

    def __init__(
        self,
        path: str,
        *,
        max_records: int = 2500,
        max_daily_summaries: int = 90,
    ) -> None:
        self.path = path
        self.max_records = max_records
        self.max_daily_summaries = max_daily_summaries
        self._records: list[TradeKnowledgeRecord] = []
        self._daily_summaries: list[DailyKnowledgeSummary] = []
        self._ids: set[str] = set()
        self._last_updated: str | None = None
        self._load()

    def _load(self) -> None:
        from pathlib import Path

        p = Path(self.path)
        if not p.exists():
            return
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            _log.warning("could not load trade knowledge %s: %s", self.path, exc)
            return
        for item in raw.get("records") or []:
            try:
                rec = TradeKnowledgeRecord.model_validate(item)
            except Exception:
                continue
            self._records.append(rec)
            self._ids.add(rec.id)
        for item in raw.get("daily_summaries") or []:
            try:
                self._daily_summaries.append(DailyKnowledgeSummary.model_validate(item))
            except Exception:
                pass
        self._last_updated = raw.get("last_updated")

    def _save(self) -> None:
        from pathlib import Path

        p = Path(self.path)
        p.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "records": [r.model_dump(mode="json") for r in self._records],
            "daily_summaries": [d.model_dump(mode="json") for d in self._daily_summaries],
            "last_updated": datetime.now(UTC).isoformat(),
        }
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(p)
        self._last_updated = payload["last_updated"]

    def _append(self, record: TradeKnowledgeRecord) -> TradeKnowledgeRecord | None:
        if record.id in self._ids:
            return None
        self._records.append(record)
        self._ids.add(record.id)
        if len(self._records) > self.max_records:
            dropped = self._records[: -self.max_records]
            for d in dropped:
                self._ids.discard(d.id)
            self._records = self._records[-self.max_records :]
        self._save()
        return record

    @property
    def record_count(self) -> int:
        return len(self._records)

    @property
    def last_updated(self) -> str | None:
        return self._last_updated

    def aggregate_stats(self) -> dict[str, int]:
        stats = {
            "entries": 0,
            "exits": 0,
            "wins": 0,
            "losses": 0,
            "flats": 0,
            "rejections": 0,
            "exit_failures": 0,
            "vetoes": 0,
        }
        for r in self._records:
            if r.event_kind == "entry":
                stats["entries"] += 1
            elif r.event_kind == "exit":
                stats["exits"] += 1
                if r.outcome == "win":
                    stats["wins"] += 1
                elif r.outcome == "loss":
                    stats["losses"] += 1
                elif r.outcome == "flat":
                    stats["flats"] += 1
            elif r.event_kind == "entry_rejected":
                stats["rejections"] += 1
            elif r.event_kind == "exit_failed":
                stats["exit_failures"] += 1
            elif r.event_kind == "research_veto":
                stats["vetoes"] += 1
        return stats

    def list_for_api(
        self,
        *,
        limit: int = 100,
        symbol: str | None = None,
        event_kind: str | None = None,
        trading_day: str | None = None,
    ) -> list[dict[str, Any]]:
        items = list(reversed(self._records))
        if symbol:
            sym = symbol.upper()
            items = [
                r
                for r in items
                if (r.symbol or "").upper() == sym or r.symbol == "SESSION"
            ]
        if event_kind:
            items = [r for r in items if r.event_kind == event_kind]
        if trading_day:
            items = [r for r in items if r.trading_day.isoformat() == trading_day]
        out: list[dict[str, Any]] = []
        for r in items[:limit]:
            out.append(
                {
                    "id": r.id,
                    "ts": r.ts.isoformat(),
                    "trading_day": r.trading_day.isoformat(),
                    "event_kind": r.event_kind,
                    "symbol": r.symbol,
                    "outcome": r.outcome,
                    "pnl_estimate": r.pnl_estimate,
                    "equity": r.equity,
                    "day_pnl": r.day_pnl,
                    "what_happened": r.what_happened,
                    "how_it_happened": r.how_it_happened,
                    "why_it_happened": r.why_it_happened,
                    "research_action": r.research_action,
                    "research_confidence": r.research_confidence,
                    "research_thesis": r.research_thesis,
                    "lessons": list(r.lessons),
                }
            )
        return out

    def daily_summaries_for_api(self, *, limit: int = 14) -> list[dict[str, Any]]:
        rows = list(reversed(self._daily_summaries))[:limit]
        return [d.model_dump(mode="json") for d in rows]

    def api_payload(
        self,
        *,
        limit: int = 100,
        symbol: str | None = None,
        event_kind: str | None = None,
        trading_day: str | None = None,
    ) -> dict[str, Any]:
        return {
            "file": self.path,
            "record_count": self.record_count,
            "last_updated": self.last_updated,
            "stats": self.aggregate_stats(),
            "daily_summaries": self.daily_summaries_for_api(),
            "records": self.list_for_api(
                limit=limit,
                symbol=symbol,
                event_kind=event_kind,
                trading_day=trading_day,
            ),
        }

    def recent_records(
        self,
        *,
        limit: int = 20,
        symbols: frozenset[str] | None = None,
    ) -> tuple[TradeKnowledgeRecord, ...]:
        items = self._records
        if symbols:
            items = [
                r
                for r in items
                if not r.symbol or r.symbol.upper() in symbols or r.symbol == "SESSION"
            ]
        return tuple(items[-limit:])

    def recent_for_prompt(
        self,
        *,
        symbols: Sequence[str],
        limit: int = 15,
    ) -> list[dict[str, Any]]:
        sym_set = frozenset(s.upper() for s in symbols)
        rows = self.recent_records(limit=limit * 2, symbols=sym_set)
        out: list[dict[str, Any]] = []
        for r in reversed(rows):
            if r.symbol and r.symbol != "SESSION" and r.symbol.upper() not in sym_set:
                continue
            out.append(
                {
                    "ts": r.ts.isoformat(),
                    "symbol": r.symbol,
                    "event": r.event_kind,
                    "outcome": r.outcome,
                    "pnl_estimate": r.pnl_estimate,
                    "what": r.what_happened,
                    "how": r.how_it_happened,
                    "why": r.why_it_happened,
                    "research_action": r.research_action,
                    "research_thesis": r.research_thesis,
                    "lessons": list(r.lessons),
                }
            )
            if len(out) >= limit:
                break
        return out

    def record_from_reflection(self, reflection: ClosedTradeReflection) -> TradeKnowledgeRecord | None:
        lessons = _lessons_for_close(reflection)
        rec = TradeKnowledgeRecord(
            id=record_id(
                "reflection",
                reflection.symbol,
                reflection.closed_at.isoformat(),
                reflection.exit_reason,
            ),
            ts=reflection.closed_at,
            trading_day=reflection.closed_at.date(),
            event_kind="exit",
            symbol=reflection.symbol,
            outcome=reflection.outcome,  # type: ignore[arg-type]
            pnl_estimate=reflection.pnl_estimate,
            what_happened=reflection.summary,
            how_it_happened=_how_for_exit(reflection.exit_reason),
            why_it_happened=reflection.thesis_at_entry or "No research thesis cached at entry.",
            research_thesis=reflection.thesis_at_entry or None,
            lessons=lessons,
        )
        return self._append(rec)

    def ingest_journal_events(
        self,
        events: Sequence[JournalEvent],
        *,
        thesis_by_symbol: dict[str, str] | None = None,
    ) -> int:
        """Backfill knowledge records from journal (idempotent)."""
        thesis = dict(thesis_by_symbol or {})
        added = 0
        last_research: dict[str, dict[str, Any]] = {}

        for event in sorted(events, key=lambda e: e.ts):
            sym = (event.symbol or "").upper()
            if event.kind == "research_proposal" and sym:
                meta = _parse_research_line(event.detail)
                if meta:
                    last_research[sym] = meta
                thesis[sym] = meta.get("thesis") or parse_research_thesis(event.detail)

            mapped = _JOURNAL_KIND_MAP.get(event.kind)
            if mapped is None:
                continue

            ts = datetime.fromisoformat(event.ts.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)

            research = last_research.get(sym, {})
            rec = _record_from_journal_event(
                event,
                event_kind=mapped,
                ts=ts,
                research=research,
                thesis=thesis.get(sym, ""),
            )
            if rec and self._append(rec):
                added += 1

        # Round-trip closes inferred from journal pairing
        sym_set = frozenset(thesis.keys()) if thesis else None
        for outcome in all_closed_trades_from_events(events, symbols=sym_set):
            ts = datetime.fromisoformat(outcome.exit_ts.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            pnl = outcome.day_pnl_at_exit
            outcome_label = classify_outcome(outcome.exit_reason, pnl)  # type: ignore[assignment]
            summary = summarize_reflection(
                symbol=outcome.symbol,
                outcome=outcome_label,
                exit_reason=outcome.exit_reason,
                pnl_estimate=pnl,
                thesis_at_entry=outcome.thesis_at_entry,
            )
            rec = TradeKnowledgeRecord(
                id=record_id("paired_exit", outcome.symbol, outcome.exit_ts, outcome.exit_reason),
                ts=ts,
                trading_day=ts.date(),
                event_kind="exit",
                symbol=outcome.symbol,
                outcome=outcome_label,  # type: ignore[arg-type]
                pnl_estimate=pnl,
                equity=outcome.equity_at_exit,
                day_pnl=outcome.day_pnl_at_exit,
                what_happened=summary,
                how_it_happened=_how_for_exit(outcome.exit_reason),
                why_it_happened=outcome.thesis_at_entry or "Strategy signal; research context unknown.",
                research_thesis=outcome.thesis_at_entry or None,
                strategy_detail=outcome.entry_detail[:200] if outcome.entry_detail else None,
                lessons=_lessons_from_outcome(outcome.symbol, outcome_label, outcome.exit_reason, outcome.thesis_at_entry),
            )
            if self._append(rec):
                added += 1

        return added

    def sync_from_journal(
        self,
        journal_path: str,
        *,
        limit_events: int = 3000,
        thesis_by_symbol: dict[str, str] | None = None,
    ) -> int:
        journal = Journal(journal_path)
        try:
            events = list(journal.fetch_recent(limit_events))
            events.reverse()
            return self.ingest_journal_events(events, thesis_by_symbol=thesis_by_symbol)
        finally:
            journal.close()

    def finalize_trading_day(
        self,
        trading_day: date,
        *,
        equity: float,
        day_pnl: float,
    ) -> DailyKnowledgeSummary | None:
        if any(d.trading_day == trading_day for d in self._daily_summaries):
            return None
        day_records = [r for r in self._records if r.trading_day == trading_day]
        entries = sum(1 for r in day_records if r.event_kind == "entry")
        exits = sum(1 for r in day_records if r.event_kind == "exit")
        wins = sum(1 for r in day_records if r.outcome == "win")
        losses = sum(1 for r in day_records if r.outcome == "loss")
        flats = sum(1 for r in day_records if r.outcome == "flat")
        lessons: list[str] = []
        for r in day_records:
            lessons.extend(r.lessons)
        key_lessons = tuple(dict.fromkeys(lessons))[:12]
        narrative = (
            f"{trading_day.isoformat()}: {entries} entries, {exits} exits, "
            f"day P&L ${day_pnl:+.2f} on ${equity:,.0f} virtual equity. "
            f"Outcomes: {wins} wins, {losses} losses, {flats} flat."
        )
        summary = DailyKnowledgeSummary(
            trading_day=trading_day,
            closed_at=datetime.now(UTC),
            virtual_equity=equity,
            day_pnl=day_pnl,
            entries=entries,
            exits=exits,
            wins=wins,
            losses=losses,
            flats=flats,
            key_lessons=key_lessons,
            narrative=narrative,
        )
        self._daily_summaries.append(summary)
        if len(self._daily_summaries) > self.max_daily_summaries:
            self._daily_summaries = self._daily_summaries[-self.max_daily_summaries :]
        self._save()
        return summary

    def research_context_for_symbol(
        self,
        proposal: ClaudeProposal | None,
        symbol: str,
    ) -> dict[str, Any]:
        if proposal is None or proposal.skipped:
            return {}
        idea = idea_for_symbol(proposal, symbol)
        if idea is None:
            return {}
        return {
            "action": idea.action.value,
            "confidence": idea.confidence,
            "thesis": idea.thesis,
            "instrument": idea.instrument.value,
        }


def _how_for_exit(exit_reason: str) -> str:
    reason = exit_reason.lower()
    if reason in ("take_profit", "tp"):
        return "Bracket take-profit filled at broker."
    if reason in ("stop_loss", "stop", "broker_bracket_stop", "broker_close"):
        return "Stop/bracket leg filled at broker (bot may not have exit_submitted)."
    if reason == "time_stop":
        return "Python strategy time_stop fired; bot submitted market close."
    if reason == "rsi_overbought":
        return "Python strategy RSI overbought exit fired."
    if "exit_failed" in reason or "held_for_orders" in reason:
        return "Bot attempted market close but shares were held by open bracket orders."
    return f"Exit path: {exit_reason}."


def _lessons_for_close(reflection: ClosedTradeReflection) -> tuple[str, ...]:
    return _lessons_from_outcome(
        reflection.symbol,
        reflection.outcome,
        reflection.exit_reason,
        reflection.thesis_at_entry,
    )


def _lessons_from_outcome(
    symbol: str,
    outcome: str,
    exit_reason: str,
    thesis: str,
) -> tuple[str, ...]:
    lessons: list[str] = []
    sym = symbol.upper()
    reason = exit_reason.lower()
    if outcome == "loss":
        if "broker" in reason or "bracket" in reason:
            lessons.append(f"{sym}: losses via broker bracket — verify stop width and pre-event filters.")
        if thesis and any(w in thesis.lower() for w in ("avoid", "hold", "earnings", "sidestep")):
            lessons.append(
                f"{sym}: research warned against entry but trade still opened — enforce hold/avoid gating."
            )
    if reason == "time_stop" and outcome == "win":
        lessons.append(f"{sym}: time_stop exit worked — mechanical exits can capture green when thesis was cautious.")
    if "held_for_orders" in reason:
        lessons.append(f"{sym}: exit_failed — cancel/adjust bracket legs before market close.")
    if sym == "SESSION":
        lessons.append("Session-level halt — reduce size or pause after repeated rule breaches.")
    return tuple(dict.fromkeys(lessons))


def _record_from_journal_event(
    event: JournalEvent,
    *,
    event_kind: EventKind,
    ts: datetime,
    research: dict[str, Any],
    thesis: str,
) -> TradeKnowledgeRecord | None:
    sym = (event.symbol or "").upper()
    detail = event.detail or ""
    rid = record_id(event.kind, sym, event.ts, detail[:120])

    research_action = research.get("action")
    research_conf = research.get("confidence")
    research_thesis = research.get("thesis") or thesis

    if event_kind == "entry":
        entry = parse_entry_prices(detail)
        what = f"{sym} long entered" + (f" @ ${entry:.2f}" if entry else "")
        how = "Python pullback signal passed risk; bracket order submitted to Alpaca."
        why = research_thesis or "Strategy signal without fresh research thesis."
        if research_action in ("hold", "avoid"):
            why = (
                f"Research said {research_action} but entry still filled. "
                f"Thesis: {research_thesis[:160]}"
            )
        lessons: tuple[str, ...] = ()
        if research_action in ("hold", "avoid"):
            lessons = (f"{sym}: entry despite research {research_action} — tighten gating.",)
        return TradeKnowledgeRecord(
            id=rid,
            ts=ts,
            trading_day=ts.date(),
            event_kind="entry",
            symbol=sym,
            outcome="n/a",
            equity=event.equity,
            day_pnl=event.day_pnl,
            what_happened=what,
            how_it_happened=how,
            why_it_happened=why,
            research_action=research_action,
            research_confidence=research_conf,
            research_thesis=research_thesis or None,
            strategy_detail=detail[:240],
            lessons=lessons,
        )

    if event_kind == "exit":
        pnl = event.day_pnl
        outcome = classify_outcome(detail, None)  # type: ignore[assignment]
        what = summarize_reflection(
            symbol=sym,
            outcome=outcome,
            exit_reason=detail,
            pnl_estimate=pnl,
            thesis_at_entry=thesis,
        )
        return TradeKnowledgeRecord(
            id=rid,
            ts=ts,
            trading_day=ts.date(),
            event_kind="exit",
            symbol=sym,
            outcome=outcome,  # type: ignore[arg-type]
            equity=event.equity,
            day_pnl=event.day_pnl,
            what_happened=what,
            how_it_happened=_how_for_exit(detail),
            why_it_happened=thesis or "See strategy entry context.",
            research_thesis=thesis or None,
            lessons=_lessons_from_outcome(sym, outcome, detail, thesis),
        )

    if event_kind == "entry_rejected":
        return TradeKnowledgeRecord(
            id=rid,
            ts=ts,
            trading_day=ts.date(),
            event_kind="entry_rejected",
            symbol=sym,
            outcome="n/a",
            equity=event.equity,
            day_pnl=event.day_pnl,
            what_happened=f"{sym} entry rejected: {detail[:160]}",
            how_it_happened="Signal or risk gate blocked order before broker submit.",
            why_it_happened=detail,
            research_action=research_action,
            research_thesis=research_thesis or None,
            lessons=(f"{sym}: rejected — {detail[:100]}",),
        )

    if event_kind == "research_veto":
        return TradeKnowledgeRecord(
            id=rid,
            ts=ts,
            trading_day=ts.date(),
            event_kind="research_veto",
            symbol=sym,
            outcome="n/a",
            what_happened=f"{sym} blocked by research: {detail}",
            how_it_happened="Research gating vetoed deterministic entry.",
            why_it_happened=detail,
            research_action=research_action,
            research_confidence=research_conf,
            research_thesis=research_thesis or None,
            lessons=(f"{sym}: research veto worked — {detail[:100]}",),
        )

    if event_kind == "exit_failed":
        return TradeKnowledgeRecord(
            id=rid,
            ts=ts,
            trading_day=ts.date(),
            event_kind="exit_failed",
            symbol=sym,
            outcome="unknown",
            equity=event.equity,
            day_pnl=event.day_pnl,
            what_happened=f"{sym} exit failed: {detail[:180]}",
            how_it_happened="Market close rejected; shares likely held_for_orders on bracket.",
            why_it_happened="Bracket stop/TP holds quantity; bot cannot sell until legs release.",
            lessons=(f"{sym}: fix bracket/exit sync — repeated exit_failed is operational risk.",),
        )

    if event_kind == "research_reflection":
        return TradeKnowledgeRecord(
            id=rid,
            ts=ts,
            trading_day=ts.date(),
            event_kind="research_reflection",
            symbol=sym,
            outcome="unknown",
            what_happened=detail[:300],
            how_it_happened="Post-close lesson recorded to knowledge base.",
            why_it_happened=thesis or detail[:200],
            lessons=(detail[:200],) if detail else (),
        )

    if event_kind == "session_halt":
        return TradeKnowledgeRecord(
            id=rid,
            ts=ts,
            trading_day=ts.date(),
            event_kind="session_halt",
            symbol="SESSION",
            outcome="loss" if (event.day_pnl or 0) < -1 else "flat",
            equity=event.equity,
            day_pnl=event.day_pnl,
            what_happened=f"Session halted: {detail}",
            how_it_happened="Risk engine halted new entries.",
            why_it_happened=detail,
            lessons=(f"Session halt ({detail}) — review risk and recent losses.",),
        )

    return None
