"""Track Claude vs deterministic strategy alignment and outcomes."""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from my_trade.research.models import (
    ClaudeProposal,
    ComparisonSummary,
    CycleComparison,
    TradeAction,
)

_log = logging.getLogger("my_trade.research.evaluation")


@dataclass
class ResearchEvaluationStore:
    """Append-only log of Claude/strategy comparisons and entry outcomes."""

    path: Path
    max_records: int = 500
    _comparisons: list[CycleComparison] = field(default_factory=list)
    _entries: list[dict[str, object]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.path = Path(self.path)
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            _log.warning("could not load evaluation store %s: %s", self.path, exc)
            return
        for item in raw.get("comparisons") or []:
            try:
                self._comparisons.append(CycleComparison.model_validate(item))
            except Exception:
                pass
        self._entries = list(raw.get("entries") or [])

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "comparisons": [c.model_dump(mode="json") for c in self._comparisons],
            "entries": self._entries,
        }
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def record_cycle(
        self,
        *,
        when: datetime,
        symbols: Sequence[str],
        proposal: ClaudeProposal | None,
        strategy_signals: dict[str, bool],
        min_confidence: float = 0.55,
    ) -> None:
        if proposal is None or proposal.skipped:
            return
        claude_long = {
            i.symbol.upper()
            for i in proposal.ideas
            if i.action is TradeAction.LONG
            and i.confidence >= min_confidence
        }
        for sym in symbols:
            s = sym.upper()
            strat = strategy_signals.get(s, False)
            claude = s in claude_long
            if claude and strat:
                bucket = "both_agree"
            elif claude and not strat:
                bucket = "claude_only"
            elif not claude and strat:
                bucket = "strategy_only"
            else:
                bucket = "both_pass"
            self._comparisons.append(
                CycleComparison(
                    ts=when,
                    symbol=s,
                    claude_long=claude,
                    strategy_signal=strat,
                    alignment=bucket,  # type: ignore[arg-type]
                )
            )
        if len(self._comparisons) > self.max_records:
            self._comparisons = self._comparisons[-self.max_records :]
        self._save()

    def record_entry(
        self,
        *,
        symbol: str,
        when: datetime,
        claude_long: bool,
        strategy_signal: bool,
    ) -> None:
        if claude_long and strategy_signal:
            source = "both"
        elif strategy_signal:
            source = "strategy_only"
        elif claude_long:
            source = "claude_only"
        else:
            source = "unknown"
        self._entries.append(
            {
                "ts": when.isoformat(),
                "symbol": symbol.upper(),
                "source": source,
                "outcome": None,
                "pnl_estimate": None,
            }
        )
        self._save()

    def record_outcome(
        self,
        *,
        symbol: str,
        outcome: str,
        pnl_estimate: float | None,
        when: datetime,
    ) -> None:
        sym = symbol.upper()
        for entry in reversed(self._entries):
            if entry.get("symbol") == sym and entry.get("outcome") is None:
                entry["outcome"] = outcome
                entry["pnl_estimate"] = pnl_estimate
                entry["closed_at"] = when.isoformat()
                break
        self._save()

    def summary(self, *, window: int = 50) -> ComparisonSummary:
        recent = self._comparisons[-window:]
        both_agree = sum(1 for c in recent if c.alignment == "both_agree")
        claude_only = sum(1 for c in recent if c.alignment == "claude_only")
        strategy_only = sum(1 for c in recent if c.alignment == "strategy_only")
        both_pass = sum(1 for c in recent if c.alignment == "both_pass")

        closed = [e for e in self._entries if e.get("outcome") is not None][-window:]
        by_source: dict[str, list[float]] = {}
        for e in closed:
            src = str(e.get("source", "unknown"))
            pnl = e.get("pnl_estimate")
            if isinstance(pnl, (int, float)):
                by_source.setdefault(src, []).append(float(pnl))

        avg_pnl_by_source = {
            src: (sum(vals) / len(vals) if vals else 0.0) for src, vals in by_source.items()
        }
        return ComparisonSummary(
            sample_cycles=len(recent),
            both_agree=both_agree,
            claude_only=claude_only,
            strategy_only=strategy_only,
            both_pass=both_pass,
            entries_tracked=len(self._entries),
            closed_trades=len(closed),
            avg_pnl_by_source=avg_pnl_by_source,
        )
