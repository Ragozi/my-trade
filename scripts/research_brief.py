"""Build and save the daily research brief (no orders, optional LLM).

Run with:  python -m scripts.research_brief   (or: poe research-brief)
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from my_trade.config import load_settings  # noqa: E402
from my_trade.research.brief import build_research_brief, save_brief  # noqa: E402

log = logging.getLogger("my_trade.research_brief")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build research brief from journal.")
    parser.add_argument(
        "--hours",
        type=int,
        default=48,
        help="Journal lookback window (default 48)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    settings = load_settings()

    brief = build_research_brief(
        journal_path=settings.runtime.journal_db,
        daily_state_path=settings.runtime.daily_state_file,
        memory_path=settings.research.memory_file,
        lookback_hours=args.hours,
    )
    path = save_brief(settings.research.brief_file, brief)
    log.info(
        "Wrote brief to %s (%d event kinds, %d warnings)",
        path,
        len(brief.get("event_counts") or {}),
        len(brief.get("warnings") or []),
    )
    for warning in brief.get("warnings") or []:
        log.warning("  %s", warning)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
