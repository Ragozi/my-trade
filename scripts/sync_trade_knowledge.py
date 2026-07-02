"""Backfill logs/trade_knowledge.json from the full journal.

Run:  python -m scripts.sync_trade_knowledge
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from my_trade.config import load_settings  # noqa: E402
from my_trade.research.factory import (  # noqa: E402
    build_research_memory,
    build_trade_knowledge,
)

log = logging.getLogger("sync_trade_knowledge")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    settings = load_settings()
    store = build_trade_knowledge(settings)
    before = store.record_count

    thesis: dict[str, str] | None = None
    memory = build_research_memory(settings)
    if memory is not None:
        memory.enrich_from_journal(
            settings.runtime.journal_db,
            candidate_symbols=settings.symbols,
        )
        thesis = memory.thesis_cache

    added = store.sync_from_journal(
        settings.runtime.journal_db,
        limit_events=50_000,
        thesis_by_symbol=thesis,
    )
    after = store.record_count
    log.info(
        "Trade knowledge synced | file=%s | added=%d | total=%d (was %d)",
        settings.research.knowledge_file,
        added,
        after,
        before,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
