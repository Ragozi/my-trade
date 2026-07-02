"""Research-backed context for the operator watchlist."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from my_trade.observability.journal import JournalEvent

_PROPOSAL_RE = re.compile(
    r"^\[(?P<provider>[^\]]+)\]\s+"
    r"(?P<action>long|hold|avoid)\s+"
    r"conf=(?P<confidence>[\d.]+)\s+"
    r"(?P<instrument>\w+)\s+"
    r"(?P<horizon>\w+):\s*(?P<thesis>.*)$",
    re.IGNORECASE,
)

_STATIC_REASON = (
    "Configured in EQUITY_SYMBOLS — liquid large-cap on the pullback strategy watchlist."
)


@dataclass(frozen=True)
class SymbolIntel:
    symbol: str
    action: str | None = None
    confidence: float | None = None
    instrument: str | None = None
    time_horizon: str | None = None
    thesis: str = ""
    provider: str | None = None
    updated_at: str | None = None
    why_watch: str = ""
    recent_lesson: str = ""
    source: str = "static_config"

    def to_json(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "action": self.action,
            "confidence": self.confidence,
            "instrument": self.instrument,
            "time_horizon": self.time_horizon,
            "thesis": self.thesis,
            "provider": self.provider,
            "updated_at": self.updated_at,
            "why_watch": self.why_watch,
            "recent_lesson": self.recent_lesson,
            "source": self.source,
        }


def parse_proposal_detail(detail: str) -> dict[str, Any] | None:
    match = _PROPOSAL_RE.match(detail.strip())
    if not match:
        return None
    return {
        "provider": match.group("provider"),
        "action": match.group("action").lower(),
        "confidence": float(match.group("confidence")),
        "instrument": match.group("instrument").lower(),
        "time_horizon": match.group("horizon").lower(),
        "thesis": match.group("thesis").strip(),
    }


def load_thesis_cache(path: str | Path | None) -> dict[str, str]:
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    cache = raw.get("thesis_cache") or {}
    return {str(k).upper(): str(v) for k, v in cache.items() if v}


def load_recent_lessons(path: str | Path | None) -> dict[str, str]:
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    out: dict[str, str] = {}
    for item in raw.get("reflections") or []:
        sym = str(item.get("symbol") or "").upper()
        if not sym or sym == "SESSION":
            continue
        summary = str(item.get("llm_summary") or item.get("summary") or "").strip()
        if summary:
            out[sym] = summary
    return out


def latest_proposals_by_symbol(events: list[JournalEvent]) -> dict[str, dict[str, Any]]:
    """Most recent research_proposal per symbol (events are newest-first)."""
    out: dict[str, dict[str, Any]] = {}
    for event in events:
        if event.kind != "research_proposal" or not event.symbol:
            continue
        sym = event.symbol.upper()
        if sym in out:
            continue
        parsed = parse_proposal_detail(event.detail)
        if parsed is None:
            continue
        out[sym] = {**parsed, "updated_at": event.ts}
    return out


def build_watchlist_intel(
    symbols: list[str],
    *,
    universe_source: str,
    thesis_cache: dict[str, str] | None = None,
    lessons: dict[str, str] | None = None,
    proposals: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    thesis_cache = thesis_cache or {}
    lessons = lessons or {}
    proposals = proposals or {}
    rows: list[dict[str, Any]] = []

    for raw in symbols:
        sym = raw.upper()
        proposal = proposals.get(sym)
        thesis = (proposal or {}).get("thesis") or thesis_cache.get(sym, "")
        action = (proposal or {}).get("action")
        confidence = (proposal or {}).get("confidence")
        why_parts: list[str] = []

        if universe_source == "static_config":
            why_parts.append(_STATIC_REASON)
        else:
            why_parts.append(f"Selected by {universe_source.replace('_', ' ')} screener this cycle.")

        if action and thesis:
            stance = action.upper()
            conf_txt = f" ({confidence:.0%})" if isinstance(confidence, (int, float)) else ""
            why_parts.append(f"Research stance: {stance}{conf_txt}. {thesis}")
        elif thesis:
            why_parts.append(thesis)
        elif not why_parts:
            why_parts.append("On watchlist; awaiting research call or strategy signal.")

        row = SymbolIntel(
            symbol=sym,
            action=action,
            confidence=confidence,
            instrument=(proposal or {}).get("instrument"),
            time_horizon=(proposal or {}).get("time_horizon"),
            thesis=thesis,
            provider=(proposal or {}).get("provider"),
            updated_at=(proposal or {}).get("updated_at"),
            why_watch=" ".join(why_parts),
            recent_lesson=lessons.get(sym, ""),
            source=universe_source if sym not in proposals else "research",
        )
        rows.append(row.to_json())

    return rows
