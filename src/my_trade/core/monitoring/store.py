"""JSON persistence for ``DailyState`` (the only stateful I/O in monitoring).

Kept deliberately simple and human-readable so the daily state file can be
inspected/edited during paper trading. A corrupt or missing file degrades to
``None`` (the orchestrator then starts from an empty state and rolls over on the
first cycle) rather than crashing.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from .state import DailyState


class DailyStateStore:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> DailyState | None:
        if not self._path.exists():
            return None
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            return DailyState(
                trading_day=date.fromisoformat(raw["trading_day"]),
                start_of_day_equity=float(raw["start_of_day_equity"]),
                peak_equity=float(raw["peak_equity"]),
                entries_today={str(k): int(v) for k, v in raw.get("entries_today", {}).items()},
                position_stops={
                    str(k): float(v) for k, v in raw.get("position_stops", {}).items()
                },
                entry_times={str(k): str(v) for k, v in raw.get("entry_times", {}).items()},
                halt_lesson_logged=bool(raw.get("halt_lesson_logged", False)),
                broker_sod_equity=float(raw.get("broker_sod_equity", 0.0)),
            )
        except (ValueError, KeyError, TypeError, OSError):
            return None

    def save(self, state: DailyState) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "trading_day": state.trading_day.isoformat(),
            "start_of_day_equity": state.start_of_day_equity,
            "peak_equity": state.peak_equity,
            "entries_today": dict(state.entries_today),
            "position_stops": dict(state.position_stops),
            "entry_times": dict(state.entry_times),
            "halt_lesson_logged": state.halt_lesson_logged,
            "broker_sod_equity": state.broker_sod_equity,
        }
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        for attempt in range(5):
            try:
                tmp.replace(self._path)
                return
            except OSError:
                if attempt == 4:
                    raise
                import time

                time.sleep(0.05 * (attempt + 1))
