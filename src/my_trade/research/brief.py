"""Daily research brief — pre-digested journal stats for LLM prompts."""

from __future__ import annotations

import json
import logging
import sqlite3
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_log = logging.getLogger("my_trade.research.brief")


def _since_iso(hours: int) -> str:
    from datetime import timedelta

    return (datetime.now(UTC) - timedelta(hours=hours)).isoformat()


def build_research_brief(
    *,
    journal_path: str | Path,
    daily_state_path: str | Path | None = None,
    memory_path: str | Path | None = None,
    lookback_hours: int = 48,
) -> dict[str, Any]:
    """Aggregate journal + state into a compact brief (no LLM)."""
    jp = Path(journal_path)
    since = _since_iso(lookback_hours)
    counts: Counter[str] = Counter()
    entries: list[dict[str, str]] = []
    exits: list[dict[str, str]] = []
    rejections: Counter[str] = Counter()
    exit_failures: Counter[str] = Counter()
    latest_equity: float | None = None

    if jp.exists():
        conn = sqlite3.connect(str(jp))
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT ts, kind, symbol, detail, equity FROM events "
                "WHERE ts >= ? ORDER BY id",
                (since,),
            ).fetchall()
            for row in rows:
                kind = row["kind"]
                counts[kind] += 1
                sym = row["symbol"] or ""
                if kind == "entry_submitted":
                    entries.append(
                        {"ts": row["ts"], "symbol": sym, "detail": row["detail"][:200]}
                    )
                elif kind == "exit_submitted":
                    exits.append(
                        {"ts": row["ts"], "symbol": sym, "detail": row["detail"][:200]}
                    )
                elif kind == "entry_rejected" and row["detail"]:
                    reason = row["detail"].split(":", 1)[0].strip()[:80]
                    rejections[reason] += 1
                elif kind == "exit_failed":
                    exit_failures[sym or "?"] += 1
                if row["equity"] is not None:
                    latest_equity = float(row["equity"])
        finally:
            conn.close()

    daily: dict[str, Any] = {}
    if daily_state_path and Path(daily_state_path).exists():
        try:
            daily = json.loads(Path(daily_state_path).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            _log.warning("could not read daily state for brief: %s", exc)

    thesis_cache: dict[str, str] = {}
    reflection_count = 0
    if memory_path and Path(memory_path).exists():
        try:
            mem = json.loads(Path(memory_path).read_text(encoding="utf-8"))
            thesis_cache = {
                str(k).upper(): str(v)[:240]
                for k, v in (mem.get("thesis_cache") or {}).items()
            }
            reflection_count = len(mem.get("reflections") or [])
        except (json.JSONDecodeError, OSError) as exc:
            _log.warning("could not read memory for brief: %s", exc)

    warnings: list[str] = []
    if exit_failures:
        top = exit_failures.most_common(3)
        warnings.append(
            "exit_failed on "
            + ", ".join(f"{sym} ({n}x)" for sym, n in top)
            + " — often bracket-held shares"
        )
    if rejections.get("risk rejected: max_positions", 0) > 20:
        warnings.append("many max_positions rejections — consider rotation or max positions")

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "lookback_hours": lookback_hours,
        "event_counts": dict(counts),
        "entries": entries[-20:],
        "exits": exits[-20:],
        "top_entry_rejection_reasons": dict(rejections.most_common(8)),
        "exit_failures_by_symbol": dict(exit_failures),
        "latest_equity": latest_equity,
        "daily_state": {
            "trading_day": daily.get("trading_day"),
            "start_of_day_equity": daily.get("start_of_day_equity"),
            "peak_equity": daily.get("peak_equity"),
        },
        "thesis_cache": thesis_cache,
        "reflection_count": reflection_count,
        "warnings": warnings,
    }


def save_brief(path: str | Path, brief: dict[str, Any]) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(brief, indent=2), encoding="utf-8")
    tmp.replace(target)
    return target


def load_brief(path: str | Path) -> dict[str, Any] | None:
    target = Path(path)
    if not target.exists():
        return None
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        _log.warning("could not load research brief %s: %s", target, exc)
        return None
    return raw if isinstance(raw, dict) else None
